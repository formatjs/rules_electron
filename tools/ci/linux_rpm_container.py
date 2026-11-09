"""Execute BB artifacts in an immutable Fedora image on matching native Linux."""

from pathlib import Path
import platform
import subprocess
import sys

# Official Fedora 43 amd64 manifest, resolved 2026-11-09.
IMAGE = "docker.io/library/fedora@sha256:3a515a26e06ffe17847b46f2f71a45140180ba2e39206d9c83fde648f0767cad"

if __name__ == "__main__":
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError("Fedora smoke requires native Linux x64")
    packages = Path(sys.argv[1]).resolve()
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["docker", "run", "--rm", "--platform=linux/amd64",
                    "--mount", "type=bind,src=" + str(root) + ",dst=/workspace,readonly",
                    "--mount", "type=bind,src=" + str(packages) + ",dst=/artifacts,readonly",
                    "--workdir", "/workspace", IMAGE, "bash", "tools/ci/linux_rpm_setup.sh"], check=True, timeout=900)
