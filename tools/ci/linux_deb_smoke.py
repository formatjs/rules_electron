"""Install, update and purge the sample on a disposable native GH Linux host."""

from functools import partial
import http.server
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/desktop/tools"))
from smoke_test import display_server

PACKAGE = "rules-electron-sample-desktop"
APP_ID = "org.example.sample-desktop"
LAUNCHER = Path("/usr/bin/sample-desktop")


class FeedHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.server.corrupt and self.path.split("?", 1)[0].endswith(".deb"):
            file = Path(self.directory) / "Sample-2.0.0.deb"
            self.send_response(200)
            self.send_header("Content-Length", str(file.stat().st_size))
            self.end_headers()
            with file.open("rb") as source:
                first = source.read(1)
                self.wfile.write(bytes([first[0] ^ 1]))
                while block := source.read(1024**2):
                    self.wfile.write(block)
        else:
            super().do_GET()


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Command failed: {args}\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return result.stdout.strip()


def version():
    return command("dpkg-query", "--show", "--showformat=${Version}", PACKAGE)


def launch_smoke(expected):
    print(command(sys.executable, "examples/desktop/tools/smoke_test.py", str(LAUNCHER),
                  "--installed", "--expected-version", expected,
                  "--target-os", "linux", "--target-arch", "x64"))


def main(directory):
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError("DEB installation smoke requires native Linux x64")
    if subprocess.run(["dpkg-query", "--show", PACKAGE], capture_output=True).returncode == 0:
        raise RuntimeError("Sample package already exists; use a disposable host")
    v1 = directory / "deb_v1.deb"
    feed = directory / "deb_v2_feed"
    assert command("dpkg-deb", "--field", str(v1), "Architecture") == "amd64"
    installed = False
    try:
        installed = True
        command("sudo", "dpkg", "--install", str(v1))
        assert version() == "1.0.0-7"
        assert LAUNCHER.is_file() and LAUNCHER.stat().st_uid == 0
        desktop = Path("/usr/share/applications") / (APP_ID + ".desktop")
        command("desktop-file-validate", str(desktop))
        cache = Path("/usr/share/applications/mimeinfo.cache").read_text()
        assert "x-scheme-handler/sample-desktop=" in cache and APP_ID + ".desktop" in cache
        assert Path("/usr/share/icons/hicolor/scalable/apps/" + APP_ID + ".svg").is_file()
        launch_smoke("1.0.0")
        with tempfile.TemporaryDirectory(prefix="electron-installed-") as temporary:
            temporary = Path(temporary)
            probe = temporary / "document.sample-desktop"
            probe.write_text("sample document")
            content_type = command("gio", "info", "--attributes=standard::content-type", str(probe))
            assert "standard::content-type: application/x-sample-desktop" in content_type, content_type
            assert APP_ID + ".desktop" in command("gio", "mime", "application/x-sample-desktop")
            broker = temporary / "bin"
            broker.mkdir()
            # Headless elevation adapter. Downloader and dpkg installation remain real.
            (broker / "gksudo").write_text("#!" + sys.executable + "\n" + '''import os, pathlib, shlex, subprocess, sys
args = sys.argv[1:]
assert args[0] == "--message"
args = args[2:]
if len(args) == 1:
    args = shlex.split(args[0])
assert args[:2] == ["/bin/bash", "-c"] and len(args) == 3
command = shlex.split(args[2])
assert command[:2] == ["dpkg", "-i"]
assert command[3:] == ["||", "apt-get", "install", "-f", "-y"]
package = pathlib.Path(command[2]).resolve()
assert package.is_file() and package.name == "Sample-2.0.0.deb"
assert package.is_relative_to(pathlib.Path(os.environ["XDG_CACHE_HOME"]).resolve())
result = subprocess.run(["/usr/bin/sudo", "-n", "dpkg", "-i", str(package)])
if result.returncode:
    result = subprocess.run(["/usr/bin/sudo", "-n", "apt-get", "install", "-f", "-y"])
sys.exit(result.returncode)
''')
            (broker / "gksudo").chmod(0o755)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=str(feed)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with display_server() as display:
                    for reject in [True, False]:
                        server.corrupt = reject
                        home = temporary / ("reject" if reject else "install")
                        home.mkdir()
                        environment = dict(os.environ, DISPLAY=display, HOME=str(home),
                                           XDG_CONFIG_HOME=str(home / "config"), XDG_CACHE_HOME=str(home / "cache"),
                                           PATH=str(broker) + os.pathsep + os.environ["PATH"],
                                           RULES_ELECTRON_UPDATE_FEED=f"http://127.0.0.1:{server.server_port}/")
                        result = subprocess.run([str(LAUNCHER), "--reject-update-smoke" if reject else "--install-update-smoke",
                                                 "--disable-gpu", "--disable-dev-shm-usage"],
                                                env=environment, capture_output=True, text=True, timeout=120)
                        if result.returncode:
                            raise RuntimeError(f"Installed updater failed:\n{result.stdout}\n{result.stderr}")
                        marker = "UPDATE_HASH_REJECTED" if reject else "INSTALLED_UPDATE_SMOKE_OK"
                        assert marker in result.stdout, result.stdout + result.stderr
                        assert version() == ("1.0.0-7" if reject else "2.0.0-7")
                        print(marker)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        launch_smoke("2.0.0")
    finally:
        if installed:
            command("sudo", "dpkg", "--purge", PACKAGE)
    assert not LAUNCHER.exists()
    assert not Path("/opt/" + APP_ID).exists()
    assert not Path("/usr/share/applications/" + APP_ID + ".desktop").exists()
    assert not Path("/usr/share/mime/packages/" + APP_ID + ".xml").exists()
    assert APP_ID + ".desktop" not in Path("/usr/share/applications/mimeinfo.cache").read_text()
    print("DEB_INSTALL_UPDATE_PURGE_OK")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
