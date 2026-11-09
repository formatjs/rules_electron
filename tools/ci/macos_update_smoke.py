"""Install BB-signed public fixtures and exercise real Squirrel.Mac replacement."""

from functools import partial
import ctypes
import hashlib
import http.server
import os
from pathlib import Path
import platform
import plistlib
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time


class FeedHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        name = self.path.split("?", 1)[0]
        if name == "/Sample-1.0.0-arm64-mac.zip.blockmap":
            previous = getattr(self.server, "previous_blockmap", None)
            if previous is None:
                self.send_error(404)
                return
            data = previous.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if name != "/Sample-2.0.0-arm64-mac.zip":
            super().do_GET()
            return
        payload = Path(self.directory) / "Sample-2.0.0-arm64-mac.zip"
        size = payload.stat().st_size
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", requested)
            if match is None or not 0 <= int(match[1]) <= int(match[2]) < size:
                self.send_error(416)
                return
            start, end = map(int, match.groups())
        else:
            start, end = 0, size - 1
        self.send_response(206 if requested else 200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with self.server.lock:
            transfer = len(self.server.transfers)
            self.server.transfers.append([bool(requested), 0])
        with payload.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            first = True
            while remaining:
                block = source.read(min(1024**2, remaining))
                if not block:
                    raise RuntimeError("Update ZIP truncated during transfer")
                if first and start == 0 and self.server.corrupt:
                    block = bytes([block[0] ^ 1]) + block[1:]
                first = False
                self.wfile.write(block)
                remaining -= len(block)
                with self.server.lock:
                    self.server.transfers[transfer][1] += len(block)


def version(app):
    return plistlib.loads((app / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"]


def owned_processes(app, executables):
    root = app.resolve()
    main = root / "Contents/MacOS/sample-desktop"
    return [(pid, path.resolve() == main) for pid, path in executables if path.resolve().is_relative_to(root)]


def app_processes(app):
    result = subprocess.run(["/bin/ps", "-axo", "pid="], check=True, capture_output=True, text=True)
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    library.proc_pidpath.restype = ctypes.c_int
    executables = []
    for value in result.stdout.split():
        buffer = ctypes.create_string_buffer(4096)
        if library.proc_pidpath(int(value), buffer, len(buffer)) > 0:
            executables.append((int(value), Path(os.fsdecode(buffer.value))))
    return owned_processes(app, executables)


def stop_app(app):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, _ in app_processes(app):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        time.sleep(0.5)


def verify_fixture_identity(app, certificate):
    fingerprint = hashlib.sha1(certificate.read_bytes()).hexdigest().upper()
    requirement = f'=identifier "org.example.sample-desktop" and anchor = H"{fingerprint}"'
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "-R", requirement, str(app)], check=True)


def launch_update(app, feed, mode, home, previous):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=str(feed)))
    server.corrupt = mode == "hash"
    server.previous_blockmap = previous.with_name(previous.name + ".blockmap")
    server.lock = threading.Lock()
    server.transfers = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = dict(os.environ, HOME=str(home), RULES_ELECTRON_MAC_UPDATE_MODE=mode,
                       RULES_ELECTRON_MAC_PREVIOUS_ZIP=str(previous),
                       RULES_ELECTRON_UPDATE_FEED=f"http://127.0.0.1:{server.server_port}/")
    process = subprocess.Popen([str(app / "Contents/MacOS/sample-desktop"), "--mac-update-smoke"],
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        output, _ = process.communicate(timeout=150)
        expected = {"hash": "MAC_UPDATE_HASH_REJECTED", "signature": "MAC_UPDATE_SIGNATURE_REJECTED", "install": "MAC_INSTALLED_UPDATE_SMOKE_OK",
                    "differential": "MAC_DIFFERENTIAL_INSTALL_SMOKE_OK"}[mode]
        if process.returncode or expected not in output:
            raise RuntimeError(f"Mac update {mode} failed: {output[-4000:]}")
        print(expected, flush=True)
        if mode == "differential":
            with server.lock:
                transfers = [tuple(row) for row in server.transfers]
            size = (feed / "Sample-2.0.0-arm64-mac.zip").stat().st_size
            downloaded = sum(length for _, length in transfers)
            if not transfers or not all(ranged for ranged, _ in transfers) or not 0 < downloaded < size // 2:
                raise RuntimeError("Mac update did not reuse cached ZIP through differential ranges")
            print(f"MAC_UPDATE_DIFFERENTIAL_OK range_bytes={downloaded} zip_bytes={size}", flush=True)
        if mode in ("install", "differential"):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if version(app) == "2.0.0" and any(main and pid != process.pid for pid, main in app_processes(app)):
                    print("MAC_UPDATE_NATIVE_RELAUNCH_OK", flush=True)
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("Squirrel did not replace and relaunch the v2 app")
        elif version(app) != "1.0.0":
            raise RuntimeError("Rejected update changed installed app")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        stop_app(app)
        server.shutdown()
        server.server_close()
        thread.join(timeout=15)


def main(packages):
    if platform.system() != "Darwin" or platform.machine().lower() != "arm64":
        raise RuntimeError("Mac updater smoke requires native macOS ARM64")
    with tempfile.TemporaryDirectory(prefix="electron-mac-update-") as temporary:
        root = Path(temporary).resolve()
        certificate = packages / "macos_update_v1.cer"
        previous = packages / "macos_update_v1_feed/Sample-1.0.0-arm64-mac.zip"
        for installation, modes in [("installed", ("hash", "signature", "install")), ("differential", ("differential",))]:
            install = root / installation
            install.mkdir()
            app = install / "Sample Desktop.app"
            try:
                subprocess.run(["/usr/bin/ditto", "-x", "-k", str(previous), str(install)], check=True)
                subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
                verify_fixture_identity(app, certificate)
                if version(app) != "1.0.0":
                    raise RuntimeError("Expected initial app version 1.0.0")
                for mode in modes:
                    home = root / (installation + "-" + mode)
                    home.mkdir()
                    feed = "macos_bad_identity_feed" if mode == "signature" else "macos_update_v2_feed"
                    launch_update(app, packages / feed, mode, home, previous)
                subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
                verify_fixture_identity(app, certificate)
                subprocess.run([sys.executable, "examples/desktop/tools/smoke_test.py", str(app), "--target-os", "macos",
                                "--target-arch", "arm64", "--expected-version", "2.0.0"], check=True)
            finally:
                stop_app(app)
        print("MAC_UPDATER_LIFECYCLE_OK", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
