"""Exercise draft publication, recovery and immutable assets over real sockets."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

from electron.private.update import create_feed

TOOL = Path(sys.argv.pop(1)).resolve()
COMMIT = "a" * 40
TOKEN = "public-fixture-token"


class GitHubPublicationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.version = "2.0.0"
        self.feeds = self.make_feeds(self.version)
        self.extra = self.root / "Sample-2.0.0.dmg"
        self.extra.write_bytes(b"public extra artifact bytes")
        self.release = None
        self.objects, self.requests, self.cdn_requests = {}, [], []
        self.tag_commit, self.annotated, self.paginated = COMMIT, False, False
        self.fail_name, self.tamper, self.redirect = None, False, None
        self.mutation_redirect = None
        self.mutate_asset, self.publish_early, self.move_tag = False, False, False
        self.next_id = 1
        owner = self

        class CDN(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.cdn_requests.append(self.headers.get("Authorization"))
                data = owner.objects[int(self.path.rsplit("/", 1)[1])]["bytes"]
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.cdn = self.server(CDN)

        class API(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                parsed = urlsplit(self.path)
                path, query = unquote(parsed.path), parse_qs(parsed.query)
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                owner.requests.append((self.command, path, query, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self.reply(401)
                if self.headers.get("X-GitHub-Api-Version") != "2026-03-10":
                    return self.reply(400)
                prefix = "/repos/example-org/sample-desktop"
                if self.command == "POST" and ((owner.mutation_redirect == "create" and path == prefix + "/releases")
                                              or (owner.mutation_redirect == "upload" and path.endswith("/assets"))):
                    return self.reply(307, location=owner.cdn + "upload")
                if path == prefix + "/git/ref/tags/v" + owner.version:
                    value = {"type": "tag", "sha": "b" * 40} if owner.annotated else {"type": "commit", "sha": owner.tag_commit}
                    return self.reply(200, {"object": value})
                if path == prefix + "/git/tags/" + "b" * 40:
                    return self.reply(200, {"object": {"type": "commit", "sha": owner.tag_commit}})
                if path == prefix + "/releases":
                    if self.command == "GET":
                        page = query.get("page", ["1"])[0]
                        if owner.paginated and page == "1":
                            return self.reply(200, [{"tag_name": "old-" + str(i)} for i in range(100)])
                        return self.reply(200, [owner.release] if owner.release else [])
                    owner.release = {**json.loads(body), "id": 7, "upload_url": owner.url + prefix[1:] + "/releases/7/assets{?name,label}"}
                    return self.reply(201, owner.release)
                if path == prefix + "/releases/7":
                    if owner.publish_early and self.command == "GET":
                        owner.release["draft"] = False
                    if self.command == "PATCH":
                        owner.release.update(json.loads(body))
                    return self.reply(200, owner.release)
                if path == prefix + "/releases/7/assets":
                    if self.command == "GET":
                        if owner.mutate_asset and len(owner.objects) == len(owner.expected()):
                            next(iter(owner.objects.values()))["id"] += 1000
                        return self.reply(200, [owner.metadata(value) for value in owner.objects.values()])
                    name = query["name"][0]
                    value = {"id": owner.next_id, "name": name, "bytes": body, "state": "uploaded"}
                    owner.next_id += 1
                    if name == owner.fail_name:
                        value.update(bytes=b"", state="starter")
                    owner.objects[value["id"]] = value
                    if owner.move_tag:
                        owner.tag_commit = "c" * 40
                    return self.reply(502 if name == owner.fail_name else 201, owner.metadata(value))
                if path.startswith(prefix + "/releases/assets/"):
                    identifier = int(path.rsplit("/", 1)[1])
                    if self.command == "DELETE":
                        del owner.objects[identifier]
                        return self.reply(204)
                    if owner.redirect:
                        location = owner.cdn + "cdn/" + str(identifier) if owner.redirect == "cdn" else owner.url + self.path.lstrip("/")
                        return self.reply(302, location=location)
                    data = owner.objects[identifier]["bytes"]
                    if owner.tamper and data:
                        data = bytes([data[0] ^ 1]) + data[1:]
                    return self.reply(200, data)
                return self.reply(404)

            def reply(self, status, data=None, location=None):
                payload = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else b""
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                if location:
                    self.send_header("Location", location)
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PATCH = do_DELETE = handle_request

        self.url = self.server(API)

    def server(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/"

    def make_feeds(self, version, prefix="", channel="latest"):
        package = self.root / (prefix + "package.json")
        package.write_text(json.dumps({"version": version}))
        feeds = []
        for platform, architecture, extension, suffix in [("windows", "x64", "exe", ""), ("macos", "arm64", "zip", "-mac")]:
            artifact = self.root / (prefix + platform + "-payload")
            artifact.write_bytes((platform.encode() + bytes(range(256))) * 700)
            directory = self.root / (prefix + platform)
            create_feed(artifacts=[{"source": artifact, "name": "Sample-" + version + "-" + architecture + "." + extension}],
                        package_json=package, output=directory, platform=platform, architecture=architecture, channel=channel,
                        release_date="2026-01-02T03:04:05Z", blockmaps=["Sample-" + version + "-" + architecture + "." + extension])
            feeds.append((channel + suffix + ".yml", directory))
        return feeds

    @staticmethod
    def metadata(value):
        return {"id": value["id"], "name": value["name"], "state": value["state"], "size": len(value["bytes"])}

    def expected(self):
        return {**{path.name: path.read_bytes() for _, directory in self.feeds for path in directory.iterdir()}, self.extra.name: self.extra.read_bytes()}

    def publish(self, success=True, draft=False, extra=()):
        command = [str(TOOL), "--repository", "example-org/sample-desktop", "--commit", COMMIT,
                   "--token-env", "RELEASE_TOKEN", "--api-url", self.url, "--upload-url", self.url, "--allow-http-loopback",
                   "--asset", str(self.extra)]
        for channel, directory in self.feeds:
            command.extend(["--feed", channel + "=" + str(directory)])
        if draft:
            command.append("--draft-only")
        result = subprocess.run([*command, *extra], env={**os.environ, "RELEASE_TOKEN": TOKEN}, capture_output=True, timeout=45)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        self.assertNotIn(TOKEN.encode(), result.stdout + result.stderr)
        marker = b"GITHUB_RELEASE_STAGED\n" if draft else b"GITHUB_RELEASE_PUBLISHED\n"
        self.assertEqual(result.stdout if success else result.stderr, marker if success else b"GITHUB_RELEASE_PUBLICATION_FAILED\n")

    def test_complete_assets_before_publish_and_idempotent_public_retry(self):
        self.publish()
        self.assertFalse(self.release["draft"])
        self.assertEqual(self.release["make_latest"], "legacy")
        self.assertEqual({value["name"]: value["bytes"] for value in self.objects.values()}, self.expected())
        uploads = [query["name"][0] for method, path, query, _ in self.requests if method == "POST" and path.endswith("/assets")]
        self.assertEqual(set(uploads[-2:]), {channel for channel, _ in self.feeds})
        self.assertEqual(self.requests[-1][0], "PATCH")
        self.assertTrue(all(auth == "Bearer " + TOKEN for _, _, _, auth in self.requests))
        self.requests.clear()
        self.publish()
        self.assertTrue(all(method == "GET" for method, _, _, _ in self.requests))

    def test_draft_staging_and_resume(self):
        self.publish(draft=True)
        self.assertTrue(self.release["draft"])
        self.requests.clear()
        self.publish()
        self.assertFalse(self.release["draft"])
        self.assertFalse(any(method == "POST" for method, _, _, _ in self.requests))

    def test_interrupted_upload_repairs_only_empty_starter_asset(self):
        self.fail_name = "Sample-2.0.0-x64.exe.blockmap"
        self.publish(success=False)
        self.assertTrue(self.release["draft"])
        stable = {value["name"]: value["id"] for value in self.objects.values() if value["state"] == "uploaded"}
        self.fail_name = None
        self.requests.clear()
        self.publish()
        self.assertEqual(len([1 for method, _, _, _ in self.requests if method == "DELETE"]), 1)
        self.assertTrue(all(value["id"] == stable.get(value["name"], value["id"]) for value in self.objects.values()))

    def test_actual_download_bytes_are_verified_before_visibility(self):
        self.tamper = True
        self.publish(success=False)
        self.assertTrue(self.release["draft"])
        self.assertFalse(any(method == "PATCH" for method, _, _, _ in self.requests))
        self.tamper = False
        self.publish()

    def test_cross_origin_download_strips_authorization(self):
        self.redirect = "cdn"
        self.publish()
        self.assertTrue(self.cdn_requests)
        self.assertEqual(set(self.cdn_requests), {None})

    def test_redirect_loop_fails_without_publishing(self):
        self.redirect = "loop"
        self.publish(success=False)
        self.assertTrue(self.release["draft"])

    def test_annotated_tag_and_paginated_draft_discovery(self):
        self.annotated, self.paginated = True, True
        self.publish(draft=True)
        self.publish()
        self.assertTrue(any(query.get("page") == ["2"] for _, _, query, _ in self.requests))

    def test_wrong_commit_and_moved_tag_leave_release_unpublished(self):
        self.tag_commit = "d" * 40
        self.publish(success=False)
        self.assertIsNone(self.release)
        self.tag_commit, self.move_tag = COMMIT, True
        self.publish(success=False)
        self.assertTrue(self.release["draft"])

    def test_changed_asset_identity_is_rejected_before_publication(self):
        self.mutate_asset = True
        self.publish(success=False)
        self.assertTrue(self.release["draft"])

    def test_release_published_by_another_writer_cannot_receive_assets(self):
        self.publish_early = True
        self.publish(success=False)
        self.assertFalse(self.release["draft"])
        self.assertEqual(self.objects, {})

    def test_public_release_cannot_be_repaired_or_extended(self):
        self.publish()
        del self.objects[next(iter(self.objects))]
        self.requests.clear()
        self.publish(success=False)
        self.assertTrue(all(method == "GET" for method, _, _, _ in self.requests))

    def test_undeclared_draft_assets_are_not_deleted(self):
        self.publish(draft=True)
        self.objects[500] = {"id": 500, "name": "manual.zip", "bytes": b"manual", "state": "uploaded"}
        self.requests.clear()
        self.publish(success=False)
        self.assertIn(500, self.objects)
        self.assertTrue(self.release["draft"])
        self.assertTrue(all(method == "GET" for method, _, _, _ in self.requests))

    def test_nonempty_conflicting_assets_are_not_overwritten(self):
        self.publish(draft=True)
        value = next(iter(self.objects.values()))
        value["bytes"] = bytes([value["bytes"][0] ^ 1]) + value["bytes"][1:]
        for state in ("uploaded", "starter"):
            with self.subTest(state=state):
                value["state"] = state
                self.requests.clear()
                self.publish(success=False)
                self.assertTrue(self.release["draft"])
                self.assertTrue(all(method == "GET" for method, _, _, _ in self.requests))

    def test_invalid_inputs_fail_before_network(self):
        artifact = next(path for path in self.feeds[0][1].iterdir() if path.name.endswith(".exe"))
        artifact.write_bytes(b"changed")
        self.publish(success=False)
        self.assertEqual(self.requests, [])

    def test_version_and_asset_collisions_fail_before_network(self):
        different = self.make_feeds("3.0.0", "other-")
        (different[1][1] / "latest-mac.yml").rename(different[1][1] / "preview-mac.yml")
        self.feeds.append(("preview-mac.yml", different[1][1]))
        self.publish(success=False)
        self.assertEqual(self.requests, [])

    def test_conflicting_same_version_channels_fail_before_network(self):
        different = self.make_feeds("2.0.0", "other-")
        (different[0][1] / "latest.yml").write_text((different[0][1] / "latest.yml").read_text().replace("2026-01-02", "2026-01-03"))
        self.feeds.append(different[0])
        self.publish(success=False)
        self.assertEqual(self.requests, [])

    def test_unsafe_names_and_non_loopback_http_fail_before_network(self):
        unsafe = self.root / "Unsafe Name.exe"
        unsafe.write_bytes(b"public fixture")
        for arguments in (["--asset", str(unsafe)], ["--api-url", "http://example.invalid/"], ["--upload-url", "http://example.invalid/"]):
            with self.subTest(arguments=arguments):
                self.publish(success=False, extra=arguments)
                self.assertEqual(self.requests, [])

    def test_mutating_api_redirects_never_forward_credentials(self):
        for phase in ("create", "upload"):
            with self.subTest(phase=phase):
                self.mutation_redirect = phase
                self.publish(success=False)
                self.assertEqual(self.cdn_requests, [])
        self.assertTrue(self.release["draft"])

    def test_prerelease_is_not_promoted_to_latest(self):
        self.version = "2.1.0-beta.1"
        self.feeds = self.make_feeds(self.version, "beta-", channel="beta")
        self.publish()
        self.assertTrue(self.release["prerelease"])
        self.assertEqual(self.release["make_latest"], "false")


if __name__ == "__main__":
    unittest.main()
