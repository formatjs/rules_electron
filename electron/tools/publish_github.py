"""Publish verified update feeds through a private GitHub draft release."""

import argparse
import base64
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
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request

from electron.tools.publish_update import LIMIT, Publisher, digest, filename, read_json, snapshot


def asset_name(name):
    filename(name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("GitHub assets require ASCII filenames without spaces")
    return name


def stage(feeds, assets, output):
    paths, channels, folded, versions = {}, set(), {}, set()

    def include(path):
        name = asset_name(path.name)
        if name.casefold() in folded and folded[name.casefold()] != name:
            raise ValueError("Case-insensitive release asset collision")
        if name in paths and (path.stat().st_size != paths[name].stat().st_size or digest(path) != digest(paths[name])):
            raise ValueError("Release assets with the same name differ")
        folded[name.casefold()] = name
        paths.setdefault(name, path)

    for index, value in enumerate(feeds):
        channel, separator, directory = value.partition("=")
        if not separator:
            raise ValueError("Feed must be CHANNEL=PATH")
        asset_name(channel)
        source = Path(directory)
        for path in source.iterdir():
            asset_name(path.name)
        target = output / str(index)
        target.mkdir()
        uploads = snapshot(source, channel, target)
        versions.add(read_json(target / channel)["version"])
        channels.add(channel)
        for path in [*uploads, target / channel]:
            include(path)
    if len(versions) != 1:
        raise ValueError("Release feeds must have one shared version")
    for index, source in enumerate(assets):
        asset_name(source.name)
        if source.is_symlink():
            raise ValueError("Extra assets require regular files")
        target = output / ("extra-" + str(index))
        target.mkdir()
        descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as reader:
            if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
                raise ValueError("Extra assets require regular files")
            with (target / source.name).open("wb") as writer:
                shutil.copyfileobj(reader, writer, 1024**2)
        include(target / source.name)
    return versions.pop(), paths, channels


def identifier(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Invalid GitHub object identifier")
    return value


class GitHubPublisher:
    def __init__(self, repository, token, api_url="https://api.github.com/", upload_url="https://uploads.github.com/", allow_http_loopback=False):
        if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository) or repository.split("/")[1] in (".", ".."):
            raise ValueError("Invalid GitHub repository")
        if token is None:
            raise ValueError("GitHub release token required")
        self.api = Publisher(api_url, token, allow_http_loopback)
        self.upload = Publisher(upload_url, token, allow_http_loopback)
        self.loopback = allow_http_loopback
        self.path = "repos/" + repository
        self.headers = {**self.api.headers, "Accept": "application/vnd.github+json",
                        "User-Agent": "rules-electron-release", "X-GitHub-Api-Version": "2026-03-10"}

    def request(self, method, path, body=None, upload=False):
        transport = self.upload if upload else self.api
        headers = dict(self.headers)
        if isinstance(body, Path):
            headers.update({"Content-Type": "application/octet-stream", "Content-Length": str(body.stat().st_size)})
            with body.open("rb") as source:
                return self._open(transport, method, path, source, headers)
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        return self._open(transport, method, path, data, headers)

    @staticmethod
    def _open(transport, method, path, data, headers):
        request = Request(transport.destination + path, data=data, headers=headers, method=method)
        try:
            return transport.opener.open(request, timeout=60)
        except HTTPError as error:
            return error

    def json(self, method, path, body=None, status=200, upload=False):
        with self.request(method, path, body, upload) as response:
            if response.status != status:
                raise ValueError("GitHub request failed")
            data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("GitHub metadata too large")
        return json.loads(data)

    def listing(self, path):
        for page in range(1, 101):
            values = self.json("GET", path + f"?per_page=100&page={page}")
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError("Invalid GitHub listing")
            yield from values
            if len(values) < 100:
                return
        raise ValueError("GitHub listing exceeds pagination limit")

    def require_tag(self, tag, commit):
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Full commit SHA required")
        value = self.json("GET", self.path + "/git/ref/tags/" + quote(tag, safe=""))["object"]
        for _ in range(8):
            if value.get("type") == "commit" and value.get("sha") == commit:
                return
            if value.get("type") != "tag" or not re.fullmatch(r"[0-9a-f]{40}", value.get("sha", "")):
                break
            value = self.json("GET", self.path + "/git/tags/" + value["sha"])["object"]
        raise ValueError("Release tag does not resolve to requested commit")

    def release(self, value, tag, prerelease):
        identifier(value["id"])
        if (value.get("tag_name") != tag or type(value.get("draft")) is not bool
                or type(value.get("prerelease")) is not bool or value["prerelease"] != prerelease):
            raise ValueError("Release identity differs")
        expected = self.upload.destination + self.path + f'/releases/{value["id"]}/assets'
        if value.get("upload_url", "").split("{", 1)[0] != expected:
            raise ValueError("Unexpected release upload endpoint")
        return value

    def require_draft(self, release_id, tag, prerelease):
        value = self.release(self.json("GET", self.path + f"/releases/{release_id}"), tag, prerelease)
        if value["id"] != release_id or not value["draft"]:
            raise ValueError("Release no longer draft")

    def assets(self, release_id):
        values = {}
        for value in self.listing(self.path + f"/releases/{release_id}/assets"):
            name = asset_name(value["name"])
            if name.casefold() in {key.casefold() for key in values}:
                raise ValueError("Duplicate remote release asset")
            identifier(value["id"])
            values[name] = value
        return values

    def verify(self, asset, path):
        if (asset.get("name") != path.name or asset.get("state") != "uploaded"
                or type(asset.get("size")) is not int or asset["size"] != path.stat().st_size):
            raise ValueError("Release asset metadata differs")
        url = self.api.destination + self.path + f'/releases/assets/{identifier(asset["id"])}'
        for _ in range(5):
            parsed = urlsplit(url)
            loopback = self.loopback and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "::1")
            if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                    or not (parsed.scheme == "https" or loopback) or any(ord(c) < 33 or ord(c) == 127 for c in url)):
                raise ValueError("Invalid asset download endpoint")
            headers = {key: value for key, value in self.headers.items() if key != "Authorization"}
            if (parsed.scheme, parsed.netloc) == (urlsplit(self.api.destination).scheme, urlsplit(self.api.destination).netloc):
                headers.update(self.api.headers)
            headers["Accept"] = "application/octet-stream"
            request = Request(url, headers=headers)
            try:
                response = self.api.opener.open(request, timeout=60)
            except HTTPError as error:
                response = error
            with response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Asset redirect missing location")
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ValueError("Cannot verify release asset")
                length, actual = 0, hashlib.sha512()
                while block := response.read(min(1024**2, path.stat().st_size - length + 1)):
                    length += len(block)
                    if length > path.stat().st_size:
                        raise ValueError("Release asset bytes differ")
                    actual.update(block)
                if length != path.stat().st_size or base64.b64encode(actual.digest()).decode() != digest(path):
                    raise ValueError("Release asset bytes differ")
                return
        raise ValueError("Too many asset redirects")

    def publish(self, version, paths, channels, commit, tag=None, draft_only=False):
        tag = tag or "v" + version
        if tag not in (version, "v" + version):
            raise ValueError("Release tag must match feed version")
        prerelease = "-" in version.split("+", 1)[0]
        self.require_tag(tag, commit)
        matches = [value for value in self.listing(self.path + "/releases") if value.get("tag_name") == tag]
        if len(matches) > 1:
            raise ValueError("Ambiguous release tag")
        release = matches[0] if matches else self.json("POST", self.path + "/releases", {
            "tag_name": tag, "target_commitish": commit, "name": tag, "draft": True,
            "prerelease": prerelease, "make_latest": "false",
        }, status=201)
        release = self.release(release, tag, prerelease)
        release_id = release["id"]
        remote = self.assets(release_id)
        if set(remote) - set(paths):
            raise ValueError("Undeclared release assets")
        verified = {}
        for name in sorted(paths, key=lambda value: (value in channels, value)):
            asset = remote.get(name)
            if asset and asset.get("state") == "starter" and type(asset.get("size")) is int and asset["size"] == 0 and release["draft"]:
                self.require_draft(release_id, tag, prerelease)
                with self.request("DELETE", self.path + f'/releases/assets/{asset["id"]}') as response:
                    if response.status != 204:
                        raise ValueError("Cannot remove interrupted empty upload")
                asset = None
            if asset is None:
                self.require_draft(release_id, tag, prerelease)
                asset = self.json("POST", self.path + f"/releases/{release_id}/assets?name=" + quote(name, safe=""),
                                  paths[name], status=201, upload=True)
            self.verify(asset, paths[name])
            verified[name] = asset["id"]
        final = self.assets(release_id)
        if set(final) != set(paths) or any(final[name]["id"] != verified[name] or final[name].get("state") != "uploaded" for name in paths):
            raise ValueError("Release assets changed during publication")
        self.require_tag(tag, commit)
        if release["draft"]:
            self.require_draft(release_id, tag, prerelease)
            if not draft_only:
                result = self.release(self.json("PATCH", self.path + f"/releases/{release_id}", {
                    "draft": False, "prerelease": prerelease, "make_latest": "false" if prerelease else "legacy",
                }), tag, prerelease)
                if result["id"] != release_id or result["draft"]:
                    raise ValueError("Release did not publish")
        elif draft_only:
            raise ValueError("Release already published")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", action="append", required=True, help="CHANNEL=PATH; repeat for platform feeds")
    parser.add_argument("--asset", action="append", type=Path, default=[])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True, help="Commit resolved by existing release tag")
    parser.add_argument("--tag")
    parser.add_argument("--token-env", required=True)
    parser.add_argument("--draft-only", action="store_true")
    parser.add_argument("--api-url", default="https://api.github.com/")
    parser.add_argument("--upload-url", default="https://uploads.github.com/")
    parser.add_argument("--allow-http-loopback", action="store_true")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            version, paths, channels = stage(args.feed, args.asset, Path(temporary))
            publisher = GitHubPublisher(args.repository, os.environ[args.token_env], args.api_url, args.upload_url, args.allow_http_loopback)
            publisher.publish(version, paths, channels, args.commit, args.tag, args.draft_only)
        print("GITHUB_RELEASE_STAGED" if args.draft_only else "GITHUB_RELEASE_PUBLISHED")
    except Exception:
        print("GITHUB_RELEASE_PUBLICATION_FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
