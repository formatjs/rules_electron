"""Read logs for this repository's exact BB CI invocation."""

import json
import os
import re
import urllib.request

from buildbuddy_artifacts import NoRedirect, api_request, invocation_id


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
