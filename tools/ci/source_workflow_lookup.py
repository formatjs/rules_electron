"""Find source workflows for one exact public repository commit; emit no logs."""

import json
import os
import re
import sys
import urllib.request
from urllib.error import HTTPError

try:
    from .buildbuddy_artifacts import NoRedirect
except ImportError:
    from buildbuddy_artifacts import NoRedirect

REPOSITORY = "https://github.com/formatjs/electron"
WORKFLOWS = {"Electron source components", "Electron source cross-compile", "Electron BCR consumer"}
STATES = {"COMPLETE_INVOCATION_STATUS": "complete", "PARTIAL_INVOCATION_STATUS": "running",
          "DISCONNECTED_INVOCATION_STATUS": "disconnected"}
ERRORS = {"Exact commit required": "COMMIT", "Read-only key required": "KEY",
          "Repeated lookup page": "PAGINATION", "Lookup response exceeds limit": "RESPONSE_SIZE",
          "Invalid lookup page": "PAGE", "Invalid workflow identifier": "IDENTIFIER"}


def public_workflows(records, sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Exact commit required")
    result = {}
    for record in records:
        if (record.get("repoUrl", "").removesuffix(".git") != REPOSITORY or
                record.get("commitSha") != sha or record.get("pattern") not in WORKFLOWS):
            continue
        identifier = record.get("invocationId", "")
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", identifier):
            raise ValueError("Invalid workflow identifier")
        result[identifier] = {"id": identifier, "workflow": record["pattern"],
                              "state": STATES.get(record.get("invocationStatus"), "unknown"),
                              "success": record.get("success") is True}
    return sorted(result.values(), key=lambda row: row["id"])


def lookup(key, sha):
    public_workflows([], sha)
    if not key:
        raise ValueError("Read-only key required")
    records, complete = [], True
    for repository in (REPOSITORY, REPOSITORY + ".git"):
        token, seen = "", set()
        for _ in range(8):
            if token in seen:
                raise ValueError("Repeated lookup page")
            seen.add(token)
            request = urllib.request.Request(
                "https://formatjs.buildbuddy.io/rpc/BuildBuddyService/SearchInvocation",
                data=json.dumps({"query": {"repo_url": repository, "commit_sha": sha},
                                 "count": 100, "page_token": token}).encode(),
                headers={"Content-Type": "application/json", "x-buildbuddy-api-key": key})
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
                data = response.read(4 * 1024**2 + 1)
            if len(data) > 4 * 1024**2:
                raise ValueError("Lookup response exceeds limit")
            page = json.loads(data)
            values = page.get("invocation", [])
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError("Invalid lookup page")
            records.extend(public_workflows(values, sha))
            token = page.get("nextPageToken", "")
            if not token:
                break
        complete = complete and not token
    workflows = sorted({row["id"]: row for row in records}.values(), key=lambda row: row["id"])
    return {"commit": sha, "complete": complete and len(workflows) <= 32, "workflows": workflows[:32]}


if __name__ == "__main__":
    try:
        result = lookup(os.environ["BUILDBUDDY_API_KEY"], os.environ["BUILD_SHA"])
    except HTTPError as error:
        print("SOURCE_WORKFLOW_LOOKUP_FAILED status=" + str(error.code), file=sys.stderr)
        sys.exit(1)
    except ValueError as error:
        print("SOURCE_WORKFLOW_LOOKUP_FAILED reason=" + ERRORS.get(str(error), "RESPONSE"), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("SOURCE_WORKFLOW_LOOKUP_FAILED", file=sys.stderr)
        sys.exit(1)
    print("Source workflow lookup:", json.dumps(result, sort_keys=True))
