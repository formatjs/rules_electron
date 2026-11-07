"""Execute selected BB outputs on matching native hosts; never build here."""

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

try:
    from .smoke_shards import SHARDS, archive_name
except ImportError:
    from smoke_shards import SHARDS, archive_name

VARIANTS = {
    "linux_x86_64": ("linux", "x64"),
    "macos_aarch64": ("macos", "arm64"),
    "windows_x86_64_gnullvm": ("windows", "x64"),
    "windows_x86_64_msvc": ("windows", "x64"),
    "windows_aarch64_gnullvm": ("windows", "arm64"),
    "windows_aarch64_msvc": ("windows", "arm64"),
}


def extract_variant(archive, destination, variant):
    entries = []
    paths = set()
    size = 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if not path.parts or path.parts[0] != variant:
            continue
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename or ":" in info.filename or str(path) != info.filename:
            raise ValueError("Invalid smoke artifact path")
        if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or path in paths:
            raise ValueError("Unexpected directory, symlink or duplicate entry")
        paths.add(path)
        size += info.file_size
        if size > 4 * 1024**3 or len(paths) > 10000:
            raise ValueError("Smoke variant exceeds extraction limits")
        entries.append((info, path))
    if not entries:
        raise ValueError(f"Missing smoke variant: {variant}")
    for info, path in entries:
        output = destination / path
        output.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, output.open("wb") as file:
            shutil.copyfileobj(source, file)
        output.chmod(0o755 if (info.external_attr >> 16) & 0o111 else 0o644)


if __name__ == "__main__":
    shard = os.environ["SMOKE_SHARD"]
    name = archive_name(shard)
    variants = json.loads(os.environ["SMOKE_VARIANTS"])
    if tuple(variants) != SHARDS[shard] or any(v not in VARIANTS for v in variants):
        raise ValueError("Native smoke variants must match the complete shard")
    with ZipFile(Path("artifacts") / name) as archive, tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        for variant in variants:
            extract_variant(archive, directory, variant)
            target_os, target_arch = VARIANTS[variant]
            app = directory / variant / ("app.zip" if target_os == "macos" else "app")
            subprocess.run([
                sys.executable, "examples/desktop/tools/smoke_test.py", str(app),
                "--target-os", target_os, "--target-arch", target_arch,
            ], check=True)
            if variant == "linux_x86_64":
                subprocess.run([sys.executable, "tools/ci/linux_deb_smoke.py", str(directory / variant / "packages")], check=True)
            if variant.endswith("_msvc"):
                subprocess.run([sys.executable, "tools/ci/windows_nsis_smoke.py", str(directory / variant / "packages"), target_arch], check=True)
