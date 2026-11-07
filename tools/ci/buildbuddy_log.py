"""Read logs for this repository's exact BB CI invocation."""

import json
import os
import re
import urllib.request

from buildbuddy_artifacts import NoRedirect, api_request, invocation_id


def proto_fields(data):
    def integer(offset):
        value, shift = 0, 0
        while offset < len(data) and shift < 70:
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value, offset
            shift += 7
        raise ValueError("Invalid protobuf varint")
    result, offset = {}, 0
    while offset < len(data):
        key, offset = integer(offset)
        wire = key & 7
        if wire == 0:
            value, offset = integer(offset)
        elif wire == 2:
            size, offset = integer(offset)
            value = data[offset:offset + size]
            offset += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = data[offset:offset + size]
            offset += size
        else:
            raise ValueError("Unsupported protobuf wire type")
        if offset > len(data):
            raise ValueError("Truncated protobuf")
        result.setdefault(key >> 3, []).append(value)
    return result


def action_platforms(execution, key):
    def blob(digest):
        uri = "bytestream://formatjs.buildbuddy.io/blobs/" + digest["hash"] + "/" + str(digest["sizeBytes"])
        with api_request("GetFile", {"uri": uri}, key) as response:
            data = response.read(1024**2 + 1)
        if len(data) > 1024**2:
            raise ValueError("Diagnostic proto exceeds limit")
        return proto_fields(data)
    action = blob(execution["actionDigest"])
    digest = proto_fields(action[1][0])
    command = blob({"hash": digest[1][0].decode(), "sizeBytes": digest[2][0]})
    for owner, message, field in [("Action", action, 10), ("Command", command, 5)]:
        properties = []
        for platform in message.get(field, []):
            for entry in proto_fields(platform).get(1, []):
                property = proto_fields(entry)
                name = property.get(1, [b""])[0].decode()
                if name in ("network", "dockerNetwork", "workload-isolation-type", "container-image"):
                    properties.append({"name": name, "value": property.get(2, [b""])[0].decode()})
        print(owner + " execution platform:", json.dumps(properties))


def execution_diagnostics(log, key, expected_sha):
    identifiers = list(dict.fromkeys(re.findall(r"Invocation ID: ([0-9a-f-]{36})", log)))
    for identifier in identifiers[:3]:
        with api_request("GetInvocation", {"selector": {"invocation_id": identifier}}, key) as response:
            invocations = json.load(response).get("invocation", [])
        if len(invocations) != 1 or invocations[0].get("commitSha") != expected_sha or invocations[0].get("repoUrl", "").removesuffix(".git") != "https://github.com/formatjs/rules_electron":
            continue
        body = {"execution_lookup": {"invocation_id": identifier, "target_label": "//tests:hermetic_execution_test"}, "inline_execute_response": True}
        request = urllib.request.Request("https://formatjs.buildbuddy.io/rpc/BuildBuddyService/GetExecution",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-buildbuddy-api-key": key})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
            data = json.load(response)
        for execution in data.get("execution", []):
            if "test-setup.sh" in execution.get("commandSnippet", ""):
                action_platforms(execution, key)
            result = execution.get("executeResponse", {}).get("result", {})
            metadata = result.get("executionMetadata", {})
            for auxiliary in metadata.get("auxiliaryMetadata", []):
                summary = {"isolationType": auxiliary.get("isolationType")}
                overrides = auxiliary.get("platformOverrides", {}).get("properties", [])
                summary["overrides"] = [p for p in overrides if p.get("name") in ("network", "dockerNetwork", "workload-isolation-type", "container-image")]
                if summary["isolationType"] or summary["overrides"]:
                    print("Hermetic test executor:", json.dumps(summary))


if __name__ == "__main__":
    key = os.environ["BUILDBUDDY_API_KEY"]
    if not key:
        raise ValueError("BuildBuddy read-only key is not configured")
    identifier = invocation_id(os.environ["INVOCATION_URL"])
    selector = {"invocation_id": identifier}
    with api_request("GetInvocation", {"selector": selector}, key) as response:
        invocations = json.load(response).get("invocation", [])
    if len(invocations) != 1:
        raise ValueError("Expected one invocation")
    invocation = invocations[0]
    if (invocation.get("commitSha") != os.environ["BUILD_SHA"]
            or invocation.get("repoUrl", "").removesuffix(".git") != "https://github.com/formatjs/rules_electron"
            or invocation.get("pattern") not in ("Cross-build Electron Apps", "Test Linux assembly")):
        raise ValueError("Invocation does not match this repository's CI commit")
    token = ""
    tail = ""
    for _ in range(32):
        with api_request("GetLog", {"selector": selector, "page_token": token}, key) as response:
            page = json.load(response)
        tail = (tail + page.get("log", {}).get("contents", ""))[-24000:]
        token = page.get("nextPageToken", "")
        if not token:
            break
    print(tail)
    if invocation.get("pattern") == "Test Linux assembly":
        execution_diagnostics(tail, key, os.environ["BUILD_SHA"])
