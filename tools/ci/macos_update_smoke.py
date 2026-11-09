"""Install BB-signed public fixtures and exercise real Squirrel.Mac replacement."""

from functools import partial
import ctypes
import hashlib
import http.server
import os
from pathlib import Path
import platform
import plistlib
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
        if self.server.corrupt and self.path.split("?", 1)[0].endswith(".zip"):
            payload = Path(self.directory) / "Sample-2.0.0-arm64-mac.zip"
            self.send_response(200)
            self.send_header("Content-Length", str(payload.stat().st_size))
            self.end_headers()
            with payload.open("rb") as source:
                first = source.read(1)
                self.wfile.write(bytes([first[0] ^ 1]))
                while block := source.read(1024**2):
                    self.wfile.write(block)
        else:
            super().do_GET()


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


def launch_update(app, feed, mode, home):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=str(feed)))
    server.corrupt = mode == "hash"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = dict(os.environ, HOME=str(home), RULES_ELECTRON_MAC_UPDATE_MODE=mode,
                       RULES_ELECTRON_UPDATE_FEED=f"http://127.0.0.1:{server.server_port}/")
    process = subprocess.Popen([str(app / "Contents/MacOS/sample-desktop"), "--mac-update-smoke"],
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        output, _ = process.communicate(timeout=150)
        expected = {"hash": "MAC_UPDATE_HASH_REJECTED", "signature": "MAC_UPDATE_SIGNATURE_REJECTED", "install": "MAC_INSTALLED_UPDATE_SMOKE_OK"}[mode]
        if process.returncode or expected not in output:
            raise RuntimeError(f"Mac update {mode} failed: {output[-4000:]}")
        print(expected, flush=True)
        if mode == "install":
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
        install = root / "installed"
        install.mkdir()
        app = install / "Sample Desktop.app"
        try:
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(packages / "macos_update_v1.zip"), str(install)], check=True)
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            verify_fixture_identity(app, certificate)
            if version(app) != "1.0.0":
                raise RuntimeError("Expected initial app version 1.0.0")
            for mode, feed in [("hash", "macos_update_v2_feed"), ("signature", "macos_bad_identity_feed"), ("install", "macos_update_v2_feed")]:
                home = root / mode
                home.mkdir()
                launch_update(app, packages / feed, mode, home)
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            verify_fixture_identity(app, certificate)
            subprocess.run([sys.executable, "examples/desktop/tools/smoke_test.py", str(app), "--target-os", "macos",
                            "--target-arch", "arm64", "--expected-version", "2.0.0"], check=True)
            print("MAC_UPDATER_LIFECYCLE_OK", flush=True)
        finally:
            stop_app(app)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
