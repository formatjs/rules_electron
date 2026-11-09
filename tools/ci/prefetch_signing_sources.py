"""Fetch unchanged pinned sources through GitHub's release-asset API."""

import hashlib
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

URL = "https://api.github.com/repos/raccoons-build/bazel-openssl-cc/releases/assets/686571584"
NAME = "bazel-openssl-cc-3.5.9.bcr.1.tar.gz"
SHA256 = "165c3b25bf29909cbd0ec1506e7beb5a1200264f6d16b7946b1ee672ee0c55a0"
LIMIT = 8 * 1024 * 1024


def fetch(directory):
    destination = Path(directory) / NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != SHA256:
            raise ValueError("Signing source archive digest mismatch")
        return
    request = urllib.request.Request(URL, headers={"Accept": "application/octet-stream", "X-GitHub-Api-Version": "2022-11-28"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(LIMIT + 1)
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Signing source archive digest or size mismatch")
    destination.write_bytes(data)
    print("SIGNING_SOURCE_ARCHIVE_SHA256_OK")


if __name__ == "__main__":
    fetch(sys.argv[1])
