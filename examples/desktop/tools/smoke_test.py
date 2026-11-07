"""Run the relocated packaged app with a real display and Chromium sandbox."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile


@contextmanager
def display_server():
    read_fd, write_fd = os.pipe()
    with tempfile.TemporaryFile() as log:
        server = subprocess.Popen([
            "Xvfb", "-displayfd", str(write_fd), "-nolisten", "tcp",
            "-screen", "0", "1280x800x24",
        ], pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=log)
        os.close(write_fd)
        try:
            if not select.select([read_fd], [], [], 10)[0]:
                raise RuntimeError("Xvfb startup timed out")
            number = os.read(read_fd, 32).strip()
            if not number:
                log.seek(0)
                raise RuntimeError("Xvfb failed: " + log.read().decode())
            yield ":" + str(int(number))
        finally:
            os.close(read_fd)
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    if not shutil.which("Xvfb"):
        raise RuntimeError("Install Xvfb for the Electron smoke test")
    subprocess.run(["unshare", "--user", "--map-root-user", "true"], check=True)
    source = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        app = directory / "relocated desktop app"
        shutil.copytree(source, app)
        environment = dict(os.environ)
        environment.update({
            "HOME": str(directory),
            "XDG_CONFIG_HOME": str(directory / "config"),
            "XDG_CACHE_HOME": str(directory / "cache"),
            # Hardened fuses must ignore both variables.
            "ELECTRON_RUN_AS_NODE": "1",
            "NODE_OPTIONS": "--not-a-valid-node-option",
        })
        with display_server() as display:
            environment["DISPLAY"] = display
            result = subprocess.run([
                str(app / "sample-desktop"), "--smoke", "--disable-gpu", "--disable-dev-shm-usage",
            ], cwd=directory, env=environment, capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(f"Electron exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
        lines = [line for line in result.stdout.splitlines() if line.startswith("EXAMPLE_SMOKE_OK ")]
        assert len(lines) == 1, result.stdout + result.stderr
        report = json.loads(lines[0].removeprefix("EXAMPLE_SMOKE_OK "))
        assert report["architecture"] == "x64", report
        print(lines[0])
