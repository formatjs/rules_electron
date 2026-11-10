"""Explicit HTTP release operation; never part of artifact build actions."""

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from electron.private.update import _filename, _version

LIMIT = 16 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def filename(value):
    if not isinstance(value, str):
        raise ValueError("Invalid filename")
    try:
        return _filename(value)
    except ValueError:
        raise ValueError("Invalid filename") from None


def digest(path):
    with path.open("rb") as source:
        return base64.b64encode(hashlib.file_digest(source, "sha512").digest()).decode()


def read_json(path):
    with path.open("rb") as source:
        data = source.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Metadata too large")
    return json.loads(data)


def check_map(path, payload):
    with gzip.open(path, "rb") as source:
        data = source.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Blockmap too large")
    blockmap = json.loads(data)
    files = blockmap.get("files", [])
    if blockmap.get("version") != "2" or len(files) != 1 or files[0].get("offset") != 0:
        raise ValueError("Unsupported blockmap")
    sizes, checksums = files[0]["sizes"], files[0]["checksums"]
    if (len(sizes) != len(checksums) or any(type(s) is not int or not 0 < s <= 65536 for s in sizes)
            or sum(sizes) != payload.stat().st_size):
        raise ValueError("Invalid blockmap coverage")
    with payload.open("rb") as source:
        for size, checksum in zip(sizes, checksums):
            actual = base64.b64encode(hashlib.sha256(source.read(size)).digest()).decode()
            if checksum != actual:
                raise ValueError("Blockmap checksum mismatch")


def snapshot(feed, channel, output):
    filename(channel)
    members = list(feed.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in members):
        raise ValueError("Feed requires regular files")
    for member in members:
        filename(member.name)
        descriptor = os.open(member, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("Feed requires regular files")
            with (output / member.name).open("wb") as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
    metadata = read_json(output / channel)
    _version(metadata["version"])
    files = metadata["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("Empty artifact list")
    names, uploads = {channel.casefold()}, []
    for item in files:
        name = filename(unquote(item["url"]))
        if quote(name, safe="-._~") != item["url"] or name.casefold() in names:
            raise ValueError("Invalid or duplicate artifact URL")
        names.add(name.casefold())
        path = output / name
        if type(item["size"]) is not int or item["size"] != path.stat().st_size or item["sha512"] != digest(path):
            raise ValueError("Artifact checksum or size mismatch")
        uploads.append(path)
    if metadata["path"] != uploads[0].name or metadata["sha512"] != files[0]["sha512"]:
        raise ValueError("Legacy metadata mismatch")
    for payload in uploads[:]:
        blockmap = output / (payload.name + ".blockmap")
        if blockmap.exists():
            if blockmap.name.casefold() in names:
                raise ValueError("Blockmap filename collision")
            names.add(blockmap.name.casefold())
            check_map(blockmap, payload)
            uploads.append(blockmap)
    if {p.name for p in members} != {channel, *(p.name for p in uploads)}:
        raise ValueError("Unexpected feed member")
    return uploads


class Publisher:
    def __init__(self, destination, token=None, allow_http_loopback=False):
        url = urlsplit(destination)
        loopback = url.scheme == "http" and url.hostname in ("127.0.0.1", "::1") and allow_http_loopback
        if (not url.netloc or url.username is not None or url.password is not None
                or url.query or url.fragment or not (url.scheme == "https" or loopback)
                or any(ord(c) < 33 or ord(c) == 127 for c in destination)):
            raise ValueError("Destination requires HTTPS; HTTP allowed only for explicit loopback tests")
        if token is not None and (not token or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise ValueError("Invalid release token")
        self.destination = destination.rstrip("/") + "/"
        self.headers = {"Authorization": "Bearer " + token} if token is not None else {}
        self.opener = build_opener(NoRedirect())

    def request(self, method, name, data=None, headers=None):
        request = Request(self.destination + quote(name, safe="-._~"), data=data,
                          headers={**self.headers, **(headers or {})}, method=method)
        try:
            return self.opener.open(request, timeout=60)
        except HTTPError as error:
            return error

    def content_type(self, path):
        return "application/octet-stream"

    def put(self, path, condition):
        with path.open("rb") as source:
            headers = {**condition, "Content-Length": str(path.stat().st_size),
                       "Content-Type": self.content_type(path)}
            with self.request("PUT", path.name, source, headers) as response:
                return response.status

    def publish(self, output, channel, uploads):
        with self.request("HEAD", channel) as response:
            if response.status == 404:
                condition = {"If-None-Match": "*"}
            elif response.status == 200:
                etag = response.headers.get("ETag", "")
                if not re.fullmatch(r'"[\x21\x23-\x7e]*"', etag):
                    raise ValueError("Existing channel requires strong ETag")
                condition = {"If-Match": etag}
            else:
                raise ValueError("Channel inspection HTTP " + str(response.status))
        for path in uploads:
            status = self.put(path, {"If-None-Match": "*"})
            if status == 412:
                with self.request("GET", path.name) as response:
                    actual, length = hashlib.sha512(), 0
                    if response.status != 200:
                        raise ValueError("Existing artifact cannot be verified")
                    while chunk := response.read(min(1024 * 1024, path.stat().st_size - length + 1)):
                        length += len(chunk)
                        if length > path.stat().st_size:
                            raise ValueError("Existing artifact differs")
                        actual.update(chunk)
                    if length != path.stat().st_size or base64.b64encode(actual.digest()).decode() != digest(path):
                        raise ValueError("Existing artifact differs")
            elif status not in (200, 201, 204):
                raise ValueError("Artifact upload HTTP " + str(status))
        status = self.put(output / channel, condition)
        if status not in (200, 201, 204):
            raise ValueError("Channel upload HTTP " + str(status))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--token-env")
    parser.add_argument("--allow-http-loopback", action="store_true")
    args = parser.parse_args()
    try:
        token = os.environ[args.token_env] if args.token_env else None
        publisher = Publisher(args.destination, token, args.allow_http_loopback)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            uploads = snapshot(args.feed, args.channel, output)
            publisher.publish(output, args.channel, uploads)
        print("UPDATE_PUBLISHED")
    except Exception:
        # Server responses and exception messages can contain credentials or URLs.
        print("UPDATE_PUBLICATION_FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
