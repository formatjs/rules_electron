"""Classify exact Electron source CI failures without forwarding raw logs."""

import json
import base64
import hashlib
import os
import re
import urllib.request
import urllib.parse

from buildbuddy_artifacts import NoRedirect, api_request, invocation_id
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
        "MISSING_TARGET": r"no such target|not declared in package",
        "NO_TEST_TARGETS": r"No test targets were found|No tests found",
        "INCOMPATIBLE_TARGET": r"incompatible and cannot|target.*incompatible",
        "STRATEGY_CONFIGURATION": r"No usable strategy|strategy.*not supported|strategy.*not found|invalid strategy|No default strategy",
        "TEST_STRATEGY": r"test strategy|TestRunner",
        "ANALYSIS_FAILED": r"Analysis of target.*failed|analysis failed|loading failed",
        "FATAL_ERROR": r"FATAL|ERROR",
        "MODULE_RESOLUTION": r"Error computing the main repository mapping",
        "BUILD_FAILED": r"Build did NOT complete successfully",
        "TEST_FAILED": r"\bFAILED\b",
        "CPP_MISSING_HEADER": r"fatal error: .*file not found",
        "CPP_TYPE_ERROR": r"no matching function|cannot initialize|cannot convert|invalid operands",
        "CPP_UNDECLARED_IDENTIFIER": r"undeclared identifier|no member named",
        "LINKER_UNDEFINED_SYMBOL": r"undefined symbol|undefined reference",
        "NODE_HKDF_VECTOR": r"check failed: Node crypto HKDF vector",
        "NODE_HKDF_LENGTH": r"check failed: HKDF length boundary|check failed: oversized HKDF rejected",
        "NODE_BYTE_SWAP": r"check failed: unaligned byte swap|check failed: invalid byte count|check failed: byte swap bounds",
        "ELF_FIXTURE": r"check failed: ELF note retained",
        "POSTJECT_RESOURCE": r"check failed: embedded ELF resource bytes|check failed: missing embedded resource|check failed: ELF resource name override",
        "POSTJECT_FUSE": r"check failed: default Postject fuse",
        "TORQUE_INTERFACE_TEST": r"FAIL: test_complete_engine_interfaces_and_reproducibility",
        "TORQUE_INVALID_INPUT_TEST": r"FAIL: test_malformed_torque_(?:fails_cleanly|reports_parse_error)",
        "TORQUE_REPRODUCIBILITY": r"Torque output differs across paths and input mtimes",
        "TORQUE_ARRAY_INTERFACE": r"Regex didn't match:.*JSArray",
        "TORQUE_INTL_INTERFACE": r"Regex didn't match:.*JSCollator",
        "TORQUE_TEMPORAL_INTERFACE": r"Regex didn't match:.*JSTemporalPlainDate",
        "TORQUE_TEST_EXCEPTION": r"ERROR: test_complete_engine_interfaces_and_reproducibility|ERROR: test_malformed_torque_(?:fails_cleanly|reports_parse_error)",
        "ASSERTION_FAILURE": r"AssertionError:",
        "PROCESS_SIGNAL": r"Segmentation fault|SIGSEGV|SIGABRT|Aborted|Illegal instruction",
        "RESOURCE_EXHAUSTED": r"Out of memory|ResourceExhausted|OOMKilled",
        "SOURCE_VALIDATION": r"fingerprint mismatch|Patched file differs",
        "EXECUTABLE_NOT_FOUND": r"not found|No such file or directory|ENOENT",
        "EXECUTABLE_PERMISSION": r"Permission denied|EACCES",
        "SHARED_LIBRARY_LOAD": r"error while loading shared libraries|GLIBC_[0-9.]+.*not found",
        "PROCESS_START": r"Failed to start|Could not execute|cannot execute",
        "EXEC_FORMAT": r"exec format error",
    }
    return {category: len(re.findall(pattern, log, re.IGNORECASE)) for category, pattern in patterns.items() if re.search(pattern, log, re.IGNORECASE)}


def source_test_diagnostics(identifier, key):
    token, seen, count = "", set(), 0
    for _ in range(8):
        if token in seen:
            break
        seen.add(token)
        with api_request("GetAction", {"selector": {"invocation_id": identifier}, "page_token": token}, key) as response:
            content = response.read(8 * 1024**2 + 1)
        if len(content) > 8 * 1024**2:
            raise ValueError("Test action metadata exceeds limit")
        page = json.loads(content)
        for action in page.get("action", []):
            if not action.get("targetLabel", "").endswith(("//source:node_dependencies_test", "//tests:v8_torque_test")):
                continue
            for file in action.get("file", []):
                if file.get("name", "").rsplit("/", 1)[-1] != "test.log":
                    continue
                if file.get("contents"):
                    data = base64.b64decode(file["contents"], validate=True)
                    if len(data) > 1024**2:
                        raise ValueError("Test log exceeds limit")
                else:
                    uri = file.get("uri", "")
                    parsed = urllib.parse.urlsplit(uri)
                    digest = re.search(r"/blobs/([0-9a-f]{64})/(\d+)$", parsed.path)
                    if parsed.scheme != "bytestream" or parsed.netloc not in ("formatjs.buildbuddy.io", "remote.buildbuddy.io") or not digest or int(digest[2]) > 1024**2:
                        continue
                    with api_request("GetFile", {"uri": uri}, key) as response:
                        data = response.read(int(digest[2]) + 1)
                    if len(data) != int(digest[2]) or hashlib.sha256(data).hexdigest() != digest[1]:
                        raise ValueError("Test log digest mismatch")
                count += 1
                print("Source probe test diagnostics:", json.dumps({"log_bytes": len(data), "diagnostics": classify(data.decode("utf-8", errors="replace"))}, sort_keys=True))
        token = page.get("nextPageToken", "")
        if not token:
            break
    print("Source probe logs classified:", count)


def failed_action_diagnostics(identifier, key):
    request = urllib.request.Request("https://formatjs.buildbuddy.io/rpc/BuildBuddyService/GetExecution",
                                     data=json.dumps({"execution_lookup": {"invocation_id": identifier}, "inline_execute_response": True}).encode(),
                                     headers={"Content-Type": "application/json", "x-buildbuddy-api-key": key})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        data = response.read(64 * 1024**2 + 1)
    if len(data) > 64 * 1024**2:
        raise ValueError("Execution diagnostics exceed limit")
    for execution in json.loads(data).get("execution", [])[:32]:
        response = execution.get("executeResponse", {})
        result = response.get("result", {})
        status = execution.get("status", {})
        exit_code = result.get("exitCode", execution.get("exitCode", 0))
        if not exit_code and not status.get("code"):
            continue
        log = status.get("message", "") + response.get("status", {}).get("message", "")
        for name in ("stdoutRaw", "stderrRaw"):
            log += base64.b64decode(result.get(name, ""), validate=True).decode("utf-8", errors="replace")
        digests = [result.get(name) for name in ("stdoutDigest", "stderrDigest")]
        digests += [file.get("digest") for file in result.get("outputFiles", []) if file.get("path", "").rsplit("/", 1)[-1] == "test.log"]
        for digest in digests:
            if not digest or not re.fullmatch(r"[0-9a-f]{64}", digest.get("hash", "")) or not 0 < int(digest.get("sizeBytes", 0)) <= 1024**2:
                continue
            uri = "bytestream://formatjs.buildbuddy.io/blobs/" + digest["hash"] + "/" + str(digest["sizeBytes"])
            with api_request("GetFile", {"uri": uri}, key) as response:
                content = response.read(1024**2 + 1)
            if len(content) > 1024**2:
                raise ValueError("Test log exceeds limit")
            log += content.decode("utf-8", errors="replace")
        print("Failed action diagnostics:", json.dumps({"exit_code": exit_code, "status_code": status.get("code", 0), "inline_result": bool(result), "log_bytes": len(log.encode()), "diagnostics": classify(log)}, sort_keys=True))


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
    log = read_log({"invocation_id": identifier}, key)
    print("Source workflow diagnostics:", json.dumps({"log_bytes": len(log.encode()), "diagnostics": classify(log)}, sort_keys=True))
    for child in root.get("childInvocations", [])[:32]:
        identifier = child["invocationId"]
        value = invocation(identifier)
        log = read_log({"invocation_id": identifier}, key)
        print("Source child:", json.dumps({"id": identifier, "success": value.get("success") is True, "log_bytes": len(log.encode()), "diagnostics": classify(log)}, sort_keys=True))
        resource_diagnostics(identifier, key)
        if value.get("invocationStatus") == "COMPLETE_INVOCATION_STATUS" and not value.get("success"):
            failed_action_diagnostics(identifier, key)
            source_test_diagnostics(identifier, key)
