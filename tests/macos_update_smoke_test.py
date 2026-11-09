"""Native updater harness confines processes and corrupts only ZIP responses."""

from functools import partial
import http.server
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
import urllib.request

from tools.ci.macos_update_smoke import FeedHandler, owned_processes


class MacosUpdateSmokeTest(unittest.TestCase):
    def test_cleanup_uses_executable_identity_and_excludes_sibling_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "Sample Desktop.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            main = app / "Contents/MacOS/sample-desktop"
            helper = app / "Contents/Frameworks/Helper.app/Contents/MacOS/helper"
            alias = root / "alias.app"
            alias.symlink_to(app, target_is_directory=True)
            paths = [(1, main), (2, helper), (3, root / "Sample Desktop.app.other/Contents/MacOS/sample-desktop"),
                     (4, root / "other/Contents/MacOS/sample-desktop"), (5, alias / "Contents/MacOS/sample-desktop")]
            self.assertEqual(owned_processes(app, paths), [(1, True), (2, False), (5, True)])

    def test_feed_corruption_preserves_metadata_length_and_uncorrupted_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"ZIP fixture bytes"
            (root / "Sample-2.0.0-arm64-mac.zip").write_bytes(payload)
            metadata = b'{"version":"2.0.0"}'
            (root / "latest-mac.yml").write_bytes(metadata)
            previous = root / "old.blockmap"
            previous.write_bytes(b"previous public map")
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=directory))
            server.lock = threading.Lock()
            server.transfers = []
            server.previous_blockmap = previous
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for corrupt in (True, False):
                    server.corrupt = corrupt
                    base = f"http://127.0.0.1:{server.server_port}/"
                    with urllib.request.urlopen(base + "latest-mac.yml?noCache=fixture") as response:
                        self.assertEqual(response.read(), metadata)
                    with urllib.request.urlopen(base + "Sample-2.0.0-arm64-mac.zip?fixture=1") as response:
                        self.assertEqual(int(response.headers["Content-Length"]), len(payload))
                        data = response.read()
                    self.assertEqual(data[1:], payload[1:])
                    self.assertEqual(data[0], payload[0] ^ (1 if corrupt else 0))
                with urllib.request.urlopen(base + "Sample-1.0.0-arm64-mac.zip.blockmap") as response:
                    self.assertEqual(response.read(), b"previous public map")
                request = urllib.request.Request(base + "Sample-2.0.0-arm64-mac.zip?range=1", headers={"Range": "bytes=4-10"})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.headers["Content-Range"], f"bytes 4-10/{len(payload)}")
                    self.assertEqual(response.read(), payload[4:11])
                for value in ("bytes=0-999", "bytes=10-4", "bytes=0-1,4-5", "bytes=-1"):
                    with self.subTest(range=value), self.assertRaises(HTTPError) as caught:
                        urllib.request.urlopen(urllib.request.Request(base + "Sample-2.0.0-arm64-mac.zip", headers={"Range": value}))
                    self.assertEqual(caught.exception.code, 416)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=10)
            self.assertEqual(server.transfers, [[False, len(payload)], [False, len(payload)], [True, 7]])


if __name__ == "__main__":
    unittest.main()
