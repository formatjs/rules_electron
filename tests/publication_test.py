"""Exercise release HTTP ordering, conflicts and failure recovery over sockets."""

import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import unquote

from electron.private.update import create_feed
from electron.tools.publish_update import Publisher

TOOL = Path(sys.argv.pop(1)).resolve()


class PublicationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        package = self.root / "package.json"
        package.write_text('{"version":"2.0.0"}')
        artifact = self.root / "artifact"
        artifact.write_bytes(bytes(range(256)) * 600)
        self.name = "Sample Setup 世界.exe"
        self.feed = self.root / "feed"
        create_feed(artifacts=[{"source": artifact, "name": self.name}],
                    package_json=package, output=self.feed, platform="windows",
                    architecture="arm64", release_date="2026-01-02T03:04:05Z",
                    blockmaps=[self.name])
        self.objects, self.requests = {}, []
        self.failure, self.redirect, self.race = None, None, False
        self.etag = '"initial"'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                name = unquote(self.path[1:])
                owner.requests.append((self.command, name, self.headers.get("Authorization")))
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                status, reply = 200, b""
                if self.headers.get("Authorization") != "Bearer fixture-token":
                    status = 401
                elif owner.redirect:
                    status = 307
                elif self.command == "HEAD":
                    status = 200 if name in owner.objects else 404
                elif self.command == "GET":
                    status = 200 if name in owner.objects else 404
                    reply = owner.objects.get(name, b"")
                elif owner.failure and name == owner.failure[0]:
                    status = owner.failure[1]
                elif name == "latest.yml" and owner.race:
                    owner.objects[name] = b"concurrent release"
                    status = 412
                elif ((self.headers.get("If-None-Match") == "*" and name in owner.objects)
                      or (name == "latest.yml" and name in owner.objects
                          and self.headers.get("If-Match") != owner.etag)):
                    status = 412
                else:
                    owner.objects[name] = body
                    status = 201
                self.send_response(status)
                self.send_header("Content-Length", str(len(reply)))
                if owner.redirect:
                    self.send_header("Location", owner.redirect)
                if name == "latest.yml" and status == 200:
                    self.send_header("ETag", owner.etag)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(reply)

            do_HEAD = do_GET = do_PUT = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = "http://127.0.0.1:" + str(server.server_port) + "/"

    def publish(self, success=True):
        result = subprocess.run(
            [str(TOOL), "--feed", str(self.feed), "--channel", "latest.yml",
             "--destination", self.url, "--allow-http-loopback", "--token-env", "RELEASE_TOKEN"],
            env={**os.environ, "RELEASE_TOKEN": "fixture-token"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        self.assertNotIn(b"fixture-token", result.stdout + result.stderr)
        self.assertEqual(result.stdout if success else result.stderr,
                         b"UPDATE_PUBLISHED\n" if success else b"UPDATE_PUBLICATION_FAILED\n")

    def test_exact_bytes_order_and_idempotent_retry(self):
        self.publish()
        self.assertEqual(self.objects, {p.name: p.read_bytes() for p in self.feed.iterdir()})
        self.assertEqual([(m, n) for m, n, _ in self.requests], [
            ("HEAD", "latest.yml"), ("PUT", self.name),
            ("PUT", self.name + ".blockmap"), ("PUT", "latest.yml"),
        ])
        self.assertTrue(all(token == "Bearer fixture-token" for _, _, token in self.requests))
        original = dict(self.objects)
        self.requests.clear()
        self.publish()
        self.assertEqual(self.objects, original)
        self.assertEqual([n for m, n, _ in self.requests if m == "GET"],
                         [self.name, self.name + ".blockmap"])

    def test_conflicting_payload_preserves_existing_channel(self):
        self.objects.update({self.name: b"other release", "latest.yml": b"old YAML"})
        self.publish(False)
        self.assertEqual(self.objects["latest.yml"], b"old YAML")
        self.assertFalse(any(m == "PUT" and n == "latest.yml" for m, n, _ in self.requests))

    def test_corruption_never_contacts_server(self):
        path = self.feed / self.name
        original = path.read_bytes()
        path.write_bytes(b"corrupt")
        self.publish(False)
        path.write_bytes(original)
        blockmap = self.feed / (self.name + ".blockmap")
        data = json.loads(gzip.decompress(blockmap.read_bytes()))
        data["files"][0]["checksums"][0] = "invalid"
        blockmap.write_bytes(gzip.compress(json.dumps(data).encode()))
        self.publish(False)
        self.assertEqual(self.requests, [])

    def test_upload_failure_recovers_without_publishing_channel(self):
        self.failure = (self.name + ".blockmap", 503)
        self.publish(False)
        self.assertNotIn("latest.yml", self.objects)
        self.failure = None
        self.publish()
        self.assertIn("latest.yml", self.objects)

    def test_async_upload_is_not_completion(self):
        self.failure = (self.name, 202)
        self.publish(False)
        self.assertNotIn("latest.yml", self.objects)

    def test_redirect_does_not_forward_credentials(self):
        self.redirect = self.url + "credential-target"
        self.publish(False)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.objects, {})

    def test_concurrent_channel_writer_wins(self):
        self.objects["latest.yml"] = b"old release"
        self.race = True
        self.publish(False)
        self.assertEqual(self.objects["latest.yml"], b"concurrent release")

    def test_unsafe_feed_members_fail_before_network(self):
        extra = self.feed / "extra"
        extra.write_bytes(b"undeclared")
        self.publish(False)
        extra.unlink()
        extra.symlink_to(self.feed / self.name)
        self.publish(False)
        self.assertEqual(self.requests, [])

    def test_existing_channel_requires_strong_etag(self):
        self.objects["latest.yml"] = b"old release"
        for etag in ('W/"weak"', ""):
            self.etag = etag
            self.publish(False)
        self.assertEqual(self.objects, {"latest.yml": b"old release"})
        self.assertTrue(all(method == "HEAD" for method, _, _ in self.requests))

    def test_destination_and_token_validation(self):
        for url in ("http://example.com/", "http://localhost/", "https://user:secret@example.com/",
                    "https://example.com/?secret", "https://example.com/#fragment"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Publisher(url, allow_http_loopback=True)
        with self.assertRaises(ValueError):
            Publisher(self.url)
        with self.assertRaises(ValueError):
            Publisher("https://example.com/", "injected\r\nheader")


if __name__ == "__main__":
    unittest.main()
