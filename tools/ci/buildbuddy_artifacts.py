"""Download one successful BB smoke shard for an exact repository commit.

API handoff follows formatjs/formatjs tools/ci/buildbuddy_artifacts.py.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import urllib.parse
import urllib.request

try:
    from .smoke_shards import archive_name
except ImportError:
    from smoke_shards import archive_name

API = "https://formatjs.buildbuddy.io/api/v1/"
ARCHIVE = "electron-cross-smoke.zip"
MAX_BYTES = 2 * 1024**3
SMOKE_WORKFLOWS = ("Cross-build Electron Apps", "Source-built desktop example")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def invocation_id(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "formatjs.buildbuddy.io":
        raise ValueError("Unexpected BuildBuddy invocation host")
    match = re.fullmatch(r"/invocation/([0-9a-f-]{36})", parsed.path)
    if not match:
        raise ValueError("Invalid BuildBuddy invocation URL")
    return match.group(1)


def artifact_uri(response, expected_sha, artifact_name=ARCHIVE, max_bytes=None):
    if max_bytes is None:
        invocations = response.get('invocation', [])
        source_linux = (len(invocations) == 1 and invocations[0].get('pattern') == 'Source-built desktop example'
                        and artifact_name == archive_name('linux-x64'))
        max_bytes = 3 * 1024**3 if source_linux else MAX_BYTES
    return _artifact_uri(response, expected_sha, artifact_name, max_bytes, require_success=True)


def source_profile_uri(response, expected_sha, artifact_name):
    if artifact_name not in ('cross-build-profile.json.gz', 'fixture-profile.json.gz'):
        raise ValueError('Only source timing profiles allow failed invocations')
    invocations = response.get('invocation', [])
    if len(invocations) != 1 or invocations[0].get('pattern') != 'Source-built desktop example':
        raise ValueError('Expected source workflow timing profile')
    return _artifact_uri(response, expected_sha, artifact_name, 64 * 1024**2, require_success=False)


def source_frontend_metrics_uri(response, expected_sha):
    invocations = response.get('invocation', [])
    if len(invocations) != 1 or invocations[0].get('pattern') != 'Source-built desktop example':
        raise ValueError('Expected source workflow frontend metrics')
    return _artifact_uri(response, expected_sha, 'source-frontend-metrics.jsonl', 1024**2, require_success=False)


def _verified_invocation(response, expected_sha, require_success):
    invocations = response.get("invocation", [])
    if len(invocations) != 1:
        raise ValueError("Expected one BuildBuddy invocation")
    invocation = invocations[0]
    if (invocation.get("commitSha") != expected_sha
            or invocation.get("repoUrl", "").removesuffix(".git") != "https://github.com/formatjs/rules_electron"
            or invocation.get("pattern") not in SMOKE_WORKFLOWS
            or (require_success and not invocation.get("success"))
            or invocation.get("invocationStatus") != "COMPLETE_INVOCATION_STATUS"):
        raise ValueError("Expected successful matrix invocation for this repository and commit")
    return invocation


def smoke_status_context(response, expected_sha):
    invocation = _verified_invocation(response, expected_sha, require_success=True)
    return ('Native Electron Smoke (source Linux x64)' if invocation['pattern'] == 'Source-built desktop example'
            else 'Native Electron Smoke')


def _artifact_uri(response, expected_sha, artifact_name, max_bytes, require_success):
    invocation = _verified_invocation(response, expected_sha, require_success)
    artifacts = [a for a in invocation.get("artifacts", []) if PurePosixPath(a.get("name", "")).name == artifact_name]
    if len(artifacts) != 1:
        raise ValueError("Expected one matching BuildBuddy artifact")
    uri = artifacts[0].get("uri", "")
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme != "bytestream" or parsed.netloc not in ("formatjs.buildbuddy.io", "remote.buildbuddy.io"):
        raise ValueError("Unexpected artifact store")
    match = re.search(r"/blobs/([0-9a-f]{64})/(\d+)$", parsed.path)
    if not match or int(match[2]) > max_bytes:
        raise ValueError("Invalid artifact digest or size")
    return uri, match[1], int(match[2])


def api_request(method, body, key):
    request = urllib.request.Request(API + method, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "x-buildbuddy-api-key": key,
    })
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=120)


if __name__ == "__main__":
    key = os.environ["BUILDBUDDY_API_KEY"]
    sha = os.environ["BUILD_SHA"]
    if not key or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("BuildBuddy read-only key and valid commit SHA required")
    identifier = invocation_id(os.environ["INVOCATION_URL"])
    name = archive_name(os.environ["SMOKE_SHARD"])
    with api_request("GetInvocation", {"selector": {"invocation_id": identifier}, "include_artifacts": True}, key) as response:
        uri, digest, size = artifact_uri(json.load(response), sha, artifact_name=name)
    output = Path("artifacts") / name
    output.parent.mkdir(exist_ok=True)
    hasher = hashlib.sha256()
    received = 0
    with api_request("GetFile", {"uri": uri}, key) as response, output.open("wb") as file:
        while block := response.read(1024**2):
            received += len(block)
            if received > size:
                raise ValueError("Artifact exceeds declared size")
            hasher.update(block)
            file.write(block)
    if received != size or hasher.hexdigest() != digest:
        output.unlink()
        raise ValueError("Artifact digest or size mismatch")
    print(f"Downloaded verified Electron shard {name} for {sha}: {size} bytes")
