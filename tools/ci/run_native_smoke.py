"""Execute selected BB outputs on matching native hosts; never build here."""

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
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
    paths = {}
    size = 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if not path.parts or path.parts[0] != variant:
            continue
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename or ":" in info.filename or str(path) + ("/" if info.is_dir() else "") != info.filename:
            raise ValueError("Invalid smoke artifact path")
        if stat.S_ISLNK(info.external_attr >> 16) or path in paths or info.is_dir() and info.file_size:
            raise ValueError("Unexpected symlink, duplicate or nonempty directory entry")
        paths[path] = info
        size += info.file_size
        if size > 4 * 1024**3 or len(paths) > 10000:
            raise ValueError("Smoke variant exceeds extraction limits")
        entries.append((info, path))
    if not entries:
        raise ValueError(f"Missing smoke variant: {variant}")
    checked = {PurePosixPath(str(path).casefold()): info for path, info in paths.items()} if variant.startswith(("windows_", "macos_")) else paths
    if len(checked) != len(paths):
        raise ValueError("Case-insensitive smoke path collision")
    for path in checked:
        if any(parent in checked and not checked[parent].is_dir() for parent in path.parents):
            raise ValueError("Smoke file/directory collision")
    for info, path in entries:
        output = destination / path
        if info.is_dir():
            output.mkdir(parents=True, exist_ok=True)
            output.chmod(0o755)
            continue
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
                release = directory / variant / "packages/release_tar.tar.gz"
                extracted = directory / variant / "tar-release"
                with tarfile.open(release, "r:gz") as archive:
                    members = archive.getmembers()
                    if not members or any(
                        PurePosixPath(member.name).parts[:1] != ("sample-desktop",)
                        or not (member.isfile() or member.isdir() or member.issym())
                        or member.uid != 0 or member.gid != 0 or member.mtime != 0
                        for member in members
                    ):
                        raise ValueError("Unexpected Linux release archive inventory")
                    archive.extractall(extracted, filter="data")
                subprocess.run([
                    sys.executable, "examples/desktop/tools/smoke_test.py", str(extracted / "sample-desktop"),
                    "--target-os", "linux", "--target-arch", "x64",
                ], check=True)
                print("TAR_RELEASE_SMOKE_OK", flush=True)
                subprocess.run([sys.executable, "tools/ci/linux_deb_smoke.py", str(directory / variant / "packages")], check=True)
            if variant.endswith("_msvc"):
                subprocess.run([sys.executable, "tools/ci/windows_nsis_smoke.py", str(directory / variant / "packages"), target_arch], check=True)
