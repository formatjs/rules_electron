"""Read logs for this repository's exact BB CI invocation."""

import json
import hashlib
import gzip
import zlib
import os
import re
import urllib.request
import urllib.error
from collections import Counter

try:
    from .buildbuddy_artifacts import NoRedirect, SMOKE_WORKFLOWS, api_request, artifact_uri, invocation_id, source_profile_uri
    from .profile_summary import decode_profile, recover_source_profile, summarize, summarize_source
    from .smoke_shards import SHARDS, archive_name
except ImportError:
    from buildbuddy_artifacts import NoRedirect, SMOKE_WORKFLOWS, api_request, artifact_uri, invocation_id, source_profile_uri
    from profile_summary import decode_profile, recover_source_profile, summarize, summarize_source
    from smoke_shards import SHARDS, archive_name


def read_log(selector, key):
    token, tail, seen = "", "", set()
    for _ in range(32):
        if token in seen:
            break
        seen.add(token)
        with api_request("GetLog", {"selector": selector, "page_token": token}, key) as response:
            page = json.load(response)
        tail = (tail + page.get("log", {}).get("contents", ""))[-24000:]
        token = page.get("nextPageToken", "")
        if not token:
            break
    return tail


def resource_diagnostics(identifier, key, max_bytes=64 * 1024**2):
    request = urllib.request.Request("https://formatjs.buildbuddy.io/rpc/BuildBuddyService/GetExecution",
                                     data=json.dumps({"execution_lookup": {"invocation_id": identifier}}).encode(),
                                     headers={"Content-Type": "application/json", "x-buildbuddy-api-key": key})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        print("BB tracked execution resources:", json.dumps({"invocation_id": identifier, "truncated": True, "reason": "SIZE_LIMIT"}, sort_keys=True))
        return
    executions = json.loads(data).get("execution", [])
    metadata = [value.get("executedActionMetadata", {}) for value in executions]
    usage = [value.get("usageStats", {}) for value in metadata]
    io = [value.get("ioStats", {}) for value in metadata]
    print("BB tracked execution resources:", json.dumps({
        "invocation_id": identifier,
        "stages": dict(Counter(str(value.get("stage", "UNKNOWN")) for value in executions)),
        "actions_with_usage": sum(bool(value) for value in usage),
        "cpu_seconds": round(sum(int(value.get("cpuNanos", 0)) for value in usage) / 1000000000, 3),
        "max_action_peak_memory_bytes": max((int(value.get("peakMemoryBytes", 0)) for value in usage), default=0),
        "worker_input_download_bytes": sum(int(value.get("fileDownloadSizeBytes", 0)) for value in io),
        "worker_output_upload_bytes": sum(int(value.get("fileUploadSizeBytes", 0)) for value in io),
    }, sort_keys=True))


def profile_diagnostics(invocation, key, sha):
    source = invocation.get('pattern') == 'Source-built desktop example'
    terminal_source = source and invocation.get('invocationStatus') == 'COMPLETE_INVOCATION_STATUS'
    for name in ["cross-build-profile.json.gz", "fixture-profile.json.gz"]:
        if (not invocation.get('success') and not terminal_source
                or not any(a.get("name", "").endswith(name) for a in invocation.get("artifacts", []))):
            continue
        if terminal_source:
            uri, digest, size = source_profile_uri({'invocation': [invocation]}, sha, name)
        else:
            uri, digest, size = artifact_uri({"invocation": [invocation]}, sha, artifact_name=name, max_bytes=64 * 1024**2)
        try:
            with api_request("GetFile", {"uri": uri}, key) as response:
                data = response.read(size + 1)
        except urllib.error.HTTPError as error:
            if not terminal_source or error.code != 404:
                raise
            print('Source profile unavailable:', json.dumps({'name': name, 'reason': 'NOT_FOUND'}))
            continue
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Profile digest or size mismatch")
        try:
            decoded = decode_profile(data)
        except (EOFError, ValueError, gzip.BadGzipFile) as error:
            if not terminal_source:
                raise
            if isinstance(error, EOFError):
                reason = 'TRUNCATED_GZIP'
                try:
                    summary = summarize_source(recover_source_profile(data))
                except (ValueError, zlib.error):
                    pass
                else:
                    print('Recovered incomplete BB source profile ' + name + ':', json.dumps(summary, sort_keys=True))
            elif isinstance(error, gzip.BadGzipFile):
                reason = 'INVALID_GZIP'
            elif isinstance(error, json.JSONDecodeError):
                reason = 'INVALID_JSON'
            elif str(error) == 'Profile exceeds expanded size limit':
                reason = 'EXPANDED_SIZE_LIMIT'
            else:
                reason = 'DECODE_FAILED'
            print('Source profile unavailable:', json.dumps({'name': name, 'reason': reason, 'compressed_bytes': size}))
            continue
        print("Verified BB profile " + name + ":", json.dumps((summarize_source if source else summarize)(decoded), sort_keys=True))
    for artifact in invocation.get("artifacts", []):
        name = artifact.get("name", "").rsplit("/", 1)[-1]
        if (name in ["electron-cross-smoke.zip"] + [archive_name(shard) for shard in SHARDS]
                and invocation.get("success") and invocation.get("invocationStatus") == "COMPLETE_INVOCATION_STATUS"):
            _, digest, size = artifact_uri({"invocation": [invocation]}, sha, artifact_name=name)
            print("Smoke archive digest:", json.dumps({"name": name, "sha256": digest, "size": size}, sort_keys=True))
    builds = []
    for child in invocation.get("childInvocations", []):
        with api_request("GetInvocation", {"selector": {"invocation_id": child["invocationId"]}}, key) as response:
            values = json.load(response).get("invocation", [])
        if len(values) != 1 or values[0].get("commitSha") != sha or values[0].get("repoUrl", "").removesuffix(".git") != "https://github.com/formatjs/rules_electron":
            raise ValueError("Child invocation does not match this repository and commit")
        value = values[0]
        duration = int(value.get("durationUsec", 0))
        builds.append({"invocation_id": child["invocationId"], "pattern": value.get("pattern"), "duration_seconds": round(duration / 1000000, 3) if duration else None, "reported_action_count": value.get("actionCount")})
        if not duration:
            print("Active BB child log:", child["invocationId"])
            print(read_log({"invocation_id": child["invocationId"]}, key)[-8000:])
        resource_diagnostics(child["invocationId"], key)
    print("BB child builds:", json.dumps(builds))


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
    with api_request("GetInvocation", {"selector": selector, "include_artifacts": True, "include_child_invocations": True}, key) as response:
        invocations = json.load(response).get("invocation", [])
    if len(invocations) != 1:
        raise ValueError("Expected one invocation")
    invocation = invocations[0]
    if (invocation.get("commitSha") != os.environ["BUILD_SHA"]
            or invocation.get("repoUrl", "").removesuffix(".git") != "https://github.com/formatjs/rules_electron"
            or invocation.get("pattern") not in (*SMOKE_WORKFLOWS, "Test Linux assembly")):
        raise ValueError("Invocation does not match this repository's CI commit")
    tail = read_log(selector, key)
    print(tail)
    print("Recent Bazel elapsed seconds:", re.findall(r"Elapsed time: ([0-9.]+)s", tail))
    if invocation.get("pattern") == "Test Linux assembly":
        execution_diagnostics(tail, key, os.environ["BUILD_SHA"])
    else:
        profile_diagnostics(invocation, key, os.environ["BUILD_SHA"])
