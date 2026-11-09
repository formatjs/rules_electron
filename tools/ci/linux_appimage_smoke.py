"""Execute BB AppImages and real electron-updater replacement on native Linux x64."""

from functools import partial
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/desktop/tools"))
from smoke_test import display_server


class FeedHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        name = unquote(urlsplit(self.path).path).lstrip("/")
        file = (Path(self.directory) / name).resolve()
        if not file.is_relative_to(Path(self.directory).resolve()) or not file.is_file():
            self.send_error(404)
            return
        if file.suffix != ".AppImage":
            super().do_GET()
            return
        size = file.stat().st_size
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", requested)
            if not match or not 0 <= int(match[1]) <= int(match[2]) < size:
                self.send_error(416)
                return
            start, end = map(int, match.groups())
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            start, end = 0, size - 1
            self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with self.server.lock:
            self.server.transfers.append((bool(requested), end - start + 1))
        with file.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                data = source.read(min(1024**2, remaining))
                if self.server.corrupt and source.tell() == len(data):
                    data = bytes([data[0] ^ 1]) + data[1:]
                self.wfile.write(data)
                remaining -= len(data)


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha512").digest()


def run(image, arguments, environment):
    result = subprocess.run([str(image), *arguments, "--disable-gpu", "--disable-dev-shm-usage"],
                            env=environment, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"AppImage exited {result.returncode}:\n{result.stdout[-2500:]}\n{result.stderr[-2500:]}")
    return result.stdout


def launch(image, expected, environment, extract):
    environment = dict(environment)
    environment.pop("APPIMAGE_EXTRACT_AND_RUN", None)
    if extract:
        environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    output = run(image, ["--smoke"], environment)
    reports = [json.loads(line.removeprefix("EXAMPLE_SMOKE_OK ")) for line in output.splitlines() if line.startswith("EXAMPLE_SMOKE_OK ")]
    assert len(reports) == 1
    assert reports[0]["architecture"] == "x64" and reports[0]["platform"] == "linux"
    assert reports[0]["app_version"] == expected and reports[0]["update_version"] == "2.0.0"


def main(packages):
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError("AppImage smoke requires native Linux x64")
    subprocess.run(["unshare", "--user", "--map-root-user", "true"], check=True)
    if not Path("/dev/fuse").exists() or not shutil.which("fusermount3"):
        raise RuntimeError("FUSE device and fusermount3 required for mounted AppImage smoke")
    packages = Path(packages).resolve()
    initial = packages / "appimage_v1.AppImage"
    feed = packages / "appimage_v2_feed"
    released = feed / "Sample-2.0.0.AppImage"
    metadata = json.loads((feed / "latest-linux.yml").read_text())
    assert metadata["files"][0]["blockMapSize"] > 0
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=str(feed)))
    server.corrupt, server.transfers, server.lock = False, [], threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="electron-appimage-") as temporary, display_server() as display:
            root = Path(temporary)
            for label, filename in [("versioned", "Sample-1.0.0.AppImage"), ("custom", "Custom Desktop.AppImage")]:
                directory = root / label
                directory.mkdir()
                image = directory / filename
                shutil.copyfile(initial, image)
                image.chmod(0o755)
                environment = dict(os.environ, DISPLAY=display, HOME=str(directory / "home"),
                                   XDG_CONFIG_HOME=str(directory / "config"), XDG_CACHE_HOME=str(directory / "cache"),
                                   RULES_ELECTRON_UPDATE_FEED=f"http://127.0.0.1:{server.server_port}/")
                for name in ("APPIMAGE", "APPDIR", "APPIMAGE_EXIT_AFTER_INSTALL", "APPIMAGE_EXTRACT_AND_RUN", "CHROME_DEVEL_SANDBOX", "ELECTRON_RUN_AS_NODE", "NODE_OPTIONS", "TARGET_APPIMAGE", "APPIMAGE_SILENT_INSTALL", "NO_CLEANUP"):
                    environment.pop(name, None)
                Path(environment["HOME"]).mkdir()
                launch(image, "1.0.0", environment, extract=False)
                print("APPIMAGE_FUSE_LAUNCH_OK " + label, flush=True)
                for reject in (True, False):
                    server.corrupt = reject
                    with server.lock:
                        server.transfers.clear()
                    profile = directory / ("reject" if reject else "install")
                    profile.mkdir()
                    update_environment = dict(environment, HOME=str(profile), XDG_CONFIG_HOME=str(profile / "config"),
                                              XDG_CACHE_HOME=str(profile / "cache"), APPIMAGE_EXTRACT_AND_RUN="1")
                    output = run(image, ["--reject-update-smoke" if reject else "--install-update-smoke"], update_environment)
                    marker = "UPDATE_HASH_REJECTED" if reject else "INSTALLED_UPDATE_SMOKE_OK"
                    assert marker in output
                    if reject:
                        assert digest(image) == digest(initial)
                        print("APPIMAGE_UPDATE_HASH_REJECTED " + label, flush=True)
                    else:
                        destination = directory / ("Sample-2.0.0.AppImage" if label == "versioned" else filename)
                        assert destination.exists() and digest(destination) == digest(released)
                        assert label != "versioned" or not image.exists()
                        assert destination.stat().st_mode & 0o111
                        with server.lock:
                            transfers = list(server.transfers)
                        transferred = sum(size for _, size in transfers)
                        assert transfers and all(ranged for ranged, _ in transfers), transfers
                        assert transferred < released.stat().st_size, transfers
                        print("APPIMAGE_DIFFERENTIAL_OK " + json.dumps(dict(case=label, downloaded=transferred, total=released.stat().st_size)), flush=True)
                        launch(destination, "2.0.0", environment, extract=True)
                        launch(destination, "2.0.0", environment, extract=False)
                        print("APPIMAGE_INSTALLED_UPDATE_SMOKE_OK " + label, flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main(sys.argv[1])
