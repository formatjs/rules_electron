"""Execute selected BB outputs on matching native hosts; never build here."""

import json
import plistlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from zipfile import ZipFile

from electron.private.archive import inventory

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


def prepare_app(directory, variant, target_os):
    root = Path(directory) / variant
    tree, archive = root / "app", root / "app.zip"
    if tree.exists() == archive.exists():
        raise ValueError("Expected exactly one native app input")
    if tree.is_dir():
        return tree
    if not archive.is_file() or target_os == "windows":
        raise ValueError("Unexpected native app input format")
    if target_os == "macos":
        return archive
    with inventory(archive, "linux") as (entries, open_entry):
        if len(entries) > 200000 or sum(entry.size for entry in entries.values()) > 4 * 1024**3:
            raise ValueError("Linux app exceeds extraction limits")
        tree.mkdir()
        for name, entry in sorted(entries.items()):
            if entry.kind == "symlink":
                continue
            output = tree / name
            output.parent.mkdir(parents=True, exist_ok=True)
            if entry.kind == "directory":
                output.mkdir(exist_ok=True)
            else:
                with open_entry(entry) as source, output.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            output.chmod(entry.mode)
        for name, entry in sorted(entries.items()):
            if entry.kind == "symlink":
                output = tree / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.symlink_to(entry.target)
    return tree


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
            app = prepare_app(directory, variant, target_os)
            subprocess.run([
                sys.executable, "examples/desktop/tools/smoke_test.py", str(app),
                "--target-os", target_os, "--target-arch", target_arch,
            ], check=True)
            if target_os in ("linux", "macos"):
                subprocess.run([sys.executable, "-m", "tools.ci.plain_links_smoke",
                                str(directory / variant / "packages/plain_links.zip"), target_os, target_arch], check=True)
            if target_os == "macos":
                from dmg_license_smoke import interactive_attach

                image = directory / variant / "packages/release_dmg.dmg"
                mount = directory / variant / "mounted-dmg"
                mount.mkdir()
                subprocess.run(["/usr/bin/hdiutil", "verify", str(image)], check=True, timeout=120)
                information = subprocess.run(["/usr/bin/hdiutil", "imageinfo", "-plist", str(image)],
                                             check=True, capture_output=True, timeout=120)
                properties = plistlib.loads(information.stdout).get('Properties', {})
                agreement = properties.get('Software License Agreement')
                print('DMG_LICENSE_IMAGEINFO ' + json.dumps({'agreement': agreement if type(agreement) is bool else None}), flush=True)
                if agreement is not True:
                    raise RuntimeError('DMG_LICENSE_METADATA_NOT_RECOGNIZED')
                attach = ["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(image)]
                license_header = b'Sample Desktop example license, version 1.'
                declined = interactive_attach(attach, b'n')
                print('DMG_LICENSE_RESPONSE ' + json.dumps({'phase': 'decline', 'exit_code': declined.returncode,
                      'header': license_header in declined.output, 'answered': declined.answered,
                      'mounted': (mount / 'Sample Desktop.app').exists()}), flush=True)
                if not declined.returncode or not declined.answered or license_header not in declined.output:
                    if not declined.returncode:
                        subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], check=True, timeout=120)
                    raise RuntimeError('DMG_LICENSE_DECLINE_FAILED')
                if (mount / 'Sample Desktop.app').exists():
                    raise RuntimeError('DMG_LICENSE_DECLINE_MOUNTED_IMAGE')
                print('DMG_LICENSE_DECLINED_OK', flush=True)
                accepted = interactive_attach(attach, b'y')
                print('DMG_LICENSE_RESPONSE ' + json.dumps({'phase': 'accept', 'exit_code': accepted.returncode,
                      'header': license_header in accepted.output, 'answered': accepted.answered,
                      'mounted': (mount / 'Sample Desktop.app').exists()}), flush=True)
                if accepted.returncode or not accepted.answered or license_header not in accepted.output:
                    if not accepted.returncode:
                        subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], check=True, timeout=120)
                    raise RuntimeError('DMG_LICENSE_ACCEPT_FAILED')
                print('DMG_LICENSE_ACCEPTED_OK', flush=True)
                try:
                    if (mount / "Applications").readlink().as_posix() != "/Applications":
                        raise ValueError("Invalid DMG Applications link")
                    subprocess.run([sys.executable, "tools/ci/dmg_finder_smoke.py", str(mount)], check=True)
                    subprocess.run([sys.executable, "examples/desktop/tools/smoke_test.py", str(mount / "Sample Desktop.app"),
                                    "--target-os", "macos", "--target-arch", target_arch], check=True)
                    print("DMG_NATIVE_SMOKE_OK", flush=True)
                finally:
                    subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], check=True, timeout=120)
                subprocess.run([sys.executable, "tools/ci/macos_update_smoke.py", str(directory / variant / "packages")], check=True)
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
                sevenzip = directory / variant / "packages/release_7z.7z"
                unpacked = directory / variant / "7z-release"
                subprocess.run(["7z", "x", "-y", "-bso0", "-bsp0", "-o" + str(unpacked), str(sevenzip)], check=True)
                subprocess.run([
                    sys.executable, "examples/desktop/tools/smoke_test.py", str(unpacked / "sample-desktop"),
                    "--target-os", "linux", "--target-arch", "x64",
                ], check=True)
                print("SEVENZIP_RELEASE_SMOKE_OK", flush=True)
                subprocess.run([sys.executable, "tools/ci/linux_appimage_smoke.py", str(directory / variant / "packages")], check=True)
                subprocess.run([sys.executable, "tools/ci/linux_deb_smoke.py", str(directory / variant / "packages")], check=True)
                subprocess.run([sys.executable, "tools/ci/linux_rpm_container.py", str(directory / variant / "packages")], check=True)
            if target_os == "windows":
                subprocess.run([sys.executable, "tools/ci/windows_elevation_smoke.py",
                                str(directory / variant / "packages"), target_arch], check=True)
            if variant.endswith("_msvc"):
                packages = directory / variant / "packages"
                subprocess.run([str(packages / "msix_reader.exe"), str(packages / "msix_probe.msix")], check=True)
                # Inherited PowerShell 7 modules cannot load in Windows PowerShell.
                powershell_environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
                subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                "tools/ci/windows_msix_smoke.ps1", "-Packages", str(packages), "-Architecture", target_arch,
                                "-Python", sys.executable],
                               check=True, env=powershell_environment)
                subprocess.run([sys.executable, "tools/ci/windows_nsis_smoke.py", str(directory / variant / "packages"), target_arch], check=True)
                subprocess.run([sys.executable, "tools/ci/windows_machine_nsis_smoke.py", str(packages), target_arch], check=True)
