"""Fetch the module lock from one successful, exact source-example BB build."""

import hashlib
import json
import os
from pathlib import Path
import re
import sys

try:
    from .buildbuddy_artifacts import api_request, artifact_uri, invocation_id
except ImportError:
    from buildbuddy_artifacts import api_request, artifact_uri, invocation_id


ARTIFACT = "source-example-MODULE.bazel.lock"
MAX_BYTES = 16 * 1024**2


def fetch_lock(invocation, sha, key):
    uri, digest, size = artifact_uri(invocation, sha, artifact_name=ARTIFACT, max_bytes=MAX_BYTES)
    if invocation["invocation"][0]["pattern"] != "Source-built desktop example":
        raise ValueError("Expected source-example workflow")
    with api_request("GetFile", {"uri": uri}, key) as response:
        data = response.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Source-example lock digest or size mismatch")
    lock = json.loads(data)
    if (not isinstance(lock, dict) or type(lock.get("lockFileVersion")) is not int
            or lock["lockFileVersion"] <= 0 or not isinstance(lock.get("registryFileHashes"), dict)
            or not isinstance(lock.get("moduleExtensions"), dict)):
        raise ValueError("Expected Bazel module lock")
    return data


def main():
    try:
        key, sha = os.environ["BUILDBUDDY_API_KEY"], os.environ["BUILD_SHA"]
        if not key or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Expected BB key and exact commit")
        identifier = invocation_id(os.environ["INVOCATION_URL"])
        with api_request("GetInvocation", {"selector": {"invocation_id": identifier}, "include_artifacts": True}, key) as response:
            data = fetch_lock(json.load(response), sha, key)
        output = Path("artifacts") / ARTIFACT
        output.parent.mkdir(exist_ok=True)
        with output.open("xb") as destination:
            destination.write(data)
    except Exception:
        print("SOURCE_EXAMPLE_LOCK_FAILED", file=sys.stderr)
        return 1
    print("SOURCE_EXAMPLE_LOCK_VERIFIED bytes=" + str(len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
