"""Read logs for this repository's exact BB CI invocation."""

import json
import os

from buildbuddy_artifacts import api_request, invocation_id


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
