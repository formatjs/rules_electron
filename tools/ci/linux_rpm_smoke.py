"""Native Fedora install/update/remove checks for BB-built RPM artifacts."""

from functools import partial
import http.server
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading

from linux_deb_smoke import APP_ID, DOCUMENT_ICON, FeedHandler, LAUNCHER, PACKAGE, command, display_server, mime_icon_smoke


class RpmFeedHandler(FeedHandler):
    extension = ".rpm"


def version():
    return command("rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", PACKAGE)


def launch(expected):
    print(command(sys.executable, "examples/desktop/tools/smoke_test.py", str(LAUNCHER),
                  "--installed", "--expected-version", expected, "--target-os", "linux", "--target-arch", "x64"), flush=True)


def main(directory):
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError("RPM smoke requires native Linux x64")
    if os.getuid() == 0:
        raise RuntimeError("RPM app smoke requires an unprivileged user")
    first, feed = directory / "rpm_v1.rpm", directory / "rpm_v2_feed"
    for package in [first, feed / "Sample-2.0.0.rpm"]:
        verification = command("rpm", "-Kv", str(package))
        assert "Header SHA256 digest: OK" in verification and "Payload SHA256 digest: OK" in verification
        assert command("rpm", "-qp", "--qf", "%{ARCH}", str(package)) == "x86_64"
        assert "gtk3" in command("rpm", "-qp", "--requires", str(package))
    try:
        command("sudo", "dnf", "-y", "install", str(first))
        assert version() == "1.0.0-7"
        assert command("rpm", "-V", PACKAGE) == ""
        assert (Path("/opt") / APP_ID / "resources/package-type").read_text().strip() == "rpm"
        helper = Path("/opt") / APP_ID / "chrome-sandbox"
        assert helper.stat().st_uid == helper.stat().st_gid == 0 and helper.stat().st_mode & 0o7777 == 0o4755
        assert DOCUMENT_ICON.is_file()
        mime_icon_smoke()
        launch("1.0.0")
        with tempfile.TemporaryDirectory(prefix="electron-rpm-") as temporary:
            temporary = Path(temporary)
            broker = temporary / "bin"
            broker.mkdir()
            # Headless elevation adapter; real dnf resolves and installs the update.
            (broker / "gksudo").write_text("#!" + sys.executable + "\n" + '''import os, pathlib, shlex, subprocess, sys
args = sys.argv[1:]
assert args[0] == "--message"
args = args[2:]
if len(args) == 1:
    args = shlex.split(args[0])
assert args[:2] == ["/bin/bash", "-c"] and len(args) == 3
command = shlex.split(args[2])
assert pathlib.Path(command[0]).name in ("dnf", "yum") and command[1:3] == ["-y", "install"] and len(command) == 4
package = pathlib.Path(command[3]).resolve()
assert package.is_file() and package.name == "Sample-2.0.0.rpm"
assert package.is_relative_to(pathlib.Path(os.environ["XDG_CACHE_HOME"]).resolve())
sys.exit(subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/dnf", "-y", "install", str(package)]).returncode)
''')
            (broker / "gksudo").chmod(0o755)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(RpmFeedHandler, directory=str(feed)))
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
                                                 "--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"],
                                                env=environment, capture_output=True, text=True, timeout=150)
                        if result.returncode:
                            raise RuntimeError("Installed RPM updater failed:\n" + result.stdout[-3000:] + result.stderr[-3000:])
                        marker = "UPDATE_HASH_REJECTED" if reject else "INSTALLED_UPDATE_SMOKE_OK"
                        assert marker in result.stdout
                        assert version() == ("1.0.0-7" if reject else "2.0.0-7")
                        print("RPM_" + marker, flush=True)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        assert command("rpm", "-V", PACKAGE) == ""
        mime_icon_smoke()
        launch("2.0.0")
    finally:
        command("sudo", "rpm", "-e", PACKAGE)
    for path in [Path("/opt") / APP_ID, LAUNCHER, DOCUMENT_ICON,
                 Path("/usr/share/applications") / (APP_ID + ".desktop"),
                 Path("/usr/share/mime/packages") / (APP_ID + ".xml")]:
        assert not path.exists(), str(path)
    print("RPM_INSTALL_UPDATE_REMOVE_OK", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
