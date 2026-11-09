"""Launch BB-built plain apps after relocation on matching Linux/macOS hosts."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from examples.desktop.tools.smoke_test import display_server
from tools.ci.run_native_smoke import prepare_app


def main(archive, target_os, target_arch):
    host_os = {"Linux": "linux", "Darwin": "macos"}.get(platform.system())
    host_arch = {"x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    if (host_os, host_arch) != (target_os, target_arch) or host_os is None:
        raise RuntimeError("Plain link smoke requires matching native Linux/macOS host")
    with tempfile.TemporaryDirectory(prefix="electron-plain-links-") as temporary:
        root = Path(temporary)
        stage = root / "relocated plain app"
        stage.mkdir()
        shutil.copyfile(archive, stage / "app.zip")
        app = prepare_app(root, stage.name, target_os)
        if target_os == "macos":
            extracted = stage / "extracted"
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(app), str(extracted)], check=True, timeout=60)
            bundles = list(extracted.glob("*.app"))
            if len(bundles) != 1:
                raise RuntimeError("Expected one plain app bundle")
            app = bundles[0]
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True, timeout=60)
            executable = app / "Contents/MacOS/sample-plain-desktop"
        else:
            executable = app / "sample-plain-desktop"
        environment = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / "config"), XDG_CACHE_HOME=str(root / "cache"))
        environment.pop("ELECTRON_RUN_AS_NODE", None)
        environment.pop("NODE_OPTIONS", None)
        with (display_server() if target_os == "linux" else nullcontext()) as display:
            if display:
                environment["DISPLAY"] = display
            result = subprocess.run([str(executable), "--disable-gpu", "--disable-dev-shm-usage", "--user-data-dir=" + str(root / "profile")],
                                    cwd=root, env=environment, capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError("Plain linked app failed: " + result.stdout[-2000:] + result.stderr[-2000:])
        prefix = "PLAIN_LINKS_SMOKE_OK "
        reports = [json.loads(line[len(prefix):]) for line in result.stdout.splitlines() if line.startswith(prefix)]
        expected_platform = "darwin" if target_os == "macos" else "linux"
        if reports != [{"platform": expected_platform, "architecture": target_arch}]:
            raise RuntimeError("Missing or mismatched plain link smoke result")
        print("PLAIN_LINKS_SMOKE_OK", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3])
