"""Classify exact Electron source CI failures without forwarding raw logs."""

import json
import os
import re

from buildbuddy_artifacts import api_request, invocation_id
from buildbuddy_log import read_log, resource_diagnostics


def classify(log):
    patterns = {
        "UNKNOWN_OPTION": r"Unrecognized option",
        "TOOLCHAIN_RESOLUTION": r"No matching toolchains|Unable to find an execution platform",
        "IMAGE_PULL": r"failed to pull|pull access denied|manifest unknown",
        "AUTHORIZATION": r"Unauthenticated|PermissionDenied|unauthorized",
        "EXECUTOR_UNAVAILABLE": r"No registered executors|No execution nodes",
        "NETWORK_POLICY_UNENFORCED": r"Build action unexpectedly completed an external TLS exchange",
        "NETWORK_UNREACHABLE": r"Network is unreachable|Temporary failure in name resolution|Could not resolve",
        "SOURCE_FETCH": r"Error downloading|download failed",
        "MISSING_BUILD_FILE": r"BUILD file not found",
        "MISSING_PACKAGE": r"no such package",
        "MODULE_RESOLUTION": r"Error computing the main repository mapping",
        "BUILD_FAILED": r"Build did NOT complete successfully",
        "TEST_FAILED": r"FAILED in",
        "RESOURCE_EXHAUSTED": r"Out of memory|ResourceExhausted|OOMKilled",
        "SOURCE_VALIDATION": r"fingerprint mismatch|Patched file differs",
    }
    return {category: len(re.findall(pattern, log, re.IGNORECASE)) for category, pattern in patterns.items() if re.search(pattern, log, re.IGNORECASE)}


if __name__ == "__main__":
    key = os.environ["BUILDBUDDY_API_KEY"]
    sha = os.environ["BUILD_SHA"]
    if not key or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Read-only key and exact commit SHA required")
    identifier = invocation_id(os.environ["INVOCATION_URL"])

    def invocation(identifier):
        with api_request("GetInvocation", {"selector": {"invocation_id": identifier}, "include_child_invocations": True}, key) as response:
            values = json.load(response).get("invocation", [])
        if len(values) != 1 or values[0].get("commitSha") != sha or values[0].get("repoUrl", "").removesuffix(".git") != "https://github.com/formatjs/electron":
            raise ValueError("Expected Electron source-overlay repository and commit")
        return values[0]

    root = invocation(identifier)
    if root.get("pattern") not in ("Electron source components", "Electron source cross-compile", "Electron BCR consumer"):
        raise ValueError("Expected an Electron source-overlay CI workflow")
    print("Source workflow diagnostics:", json.dumps(classify(read_log({"invocation_id": identifier}, key)), sort_keys=True))
    for child in root.get("childInvocations", [])[:32]:
        identifier = child["invocationId"]
        value = invocation(identifier)
        print("Source child:", json.dumps({"id": identifier, "success": value.get("success") is True, "diagnostics": classify(read_log({"invocation_id": identifier}, key))}, sort_keys=True))
        resource_diagnostics(identifier, key)
