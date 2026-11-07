"""Run the relocated packaged app with a real display and Chromium sandbox."""

import json
import argparse
import os
import platform
from contextlib import contextmanager, nullcontext
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
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--target-os", choices=["linux", "macos", "windows"], required=True)
    parser.add_argument("--target-arch", choices=["x64", "arm64"], required=True)
    args = parser.parse_args()
    host_os = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
    host_arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if (host_os, host_arch) != (args.target_os, args.target_arch):
        raise RuntimeError(f"Smoke requires native {args.target_os}/{args.target_arch}; host is {host_os}/{host_arch}")
    if host_os == "linux":
        if not shutil.which("Xvfb"):
            raise RuntimeError("Install Xvfb for the Electron smoke test")
        subprocess.run(["unshare", "--user", "--map-root-user", "true"], check=True)
    source = Path(args.app).resolve()
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        app = directory / "relocated desktop app"
        if host_os == "macos":
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(source), str(app)], check=True)
            bundles = list(app.glob("*.app"))
            if len(bundles) != 1:
                raise RuntimeError("Expected one packaged .app")
            app = bundles[0]
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            executable = app / "Contents/MacOS/sample-desktop"
        else:
            shutil.copytree(source, app)
            executable = app / ("sample-desktop.exe" if host_os == "windows" else "sample-desktop")
        environment = dict(os.environ)
        environment.update({
            "HOME": str(directory),
            "XDG_CONFIG_HOME": str(directory / "config"),
            "XDG_CACHE_HOME": str(directory / "cache"),
            "APPDATA": str(directory / "appdata"),
            "LOCALAPPDATA": str(directory / "localappdata"),
        })
        for name in ["ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"]:
            environment.pop(name, None)
        if host_os != "macos":
            environment.update(ELECTRON_RUN_AS_NODE="1", NODE_OPTIONS="--not-a-valid-node-option")
        with (display_server() if host_os == "linux" else nullcontext()) as display:
            if display:
                environment["DISPLAY"] = display
            result = subprocess.run([
                str(executable), "--smoke", "--disable-gpu", "--disable-dev-shm-usage",
            ], cwd=directory, env=environment, capture_output=True, encoding="utf-8", errors="replace", timeout=45)
        if result.returncode:
            raise RuntimeError(f"Electron exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
        lines = [line for line in result.stdout.splitlines() if line.startswith("EXAMPLE_SMOKE_OK ")]
        assert len(lines) == 1, result.stdout + result.stderr
        report = json.loads(lines[0].removeprefix("EXAMPLE_SMOKE_OK "))
        assert report["architecture"] == args.target_arch, report
        assert report["platform"] == {"linux": "linux", "macos": "darwin", "windows": "win32"}[args.target_os], report
        print(lines[0])
