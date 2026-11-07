"""Extract declared distribution ZIPs without following archive symlinks."""

import os
from pathlib import Path, PurePosixPath
import plistlib
import posixpath
import shutil
import stat
from zipfile import ZipFile


def _relative(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or str(path) != name or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError(f"Invalid runtime archive path: {name}")
    return path


def extract_runtime(archive, output, platform, exclude_files, occupied, languages=()):
    with ZipFile(archive) as source:
        roots = {i.filename.split("/")[0] for i in source.infolist() if ".app/" in i.filename}
        if platform == "macos" and len(roots) != 1:
            raise ValueError("macOS runtime ZIP must contain one .app")
        root = next(iter(roots)) if platform == "macos" else ""
        resources = "Contents/Resources" if platform == "macos" else "resources"
        entries = {}
        links = {}
        for info in source.infolist():
            original = str(_relative(info.filename.rstrip("/")))
            if info.is_dir() or original in exclude_files:
                continue
            if root:
                name = original[len(root) + 1:] if original.startswith(root + "/") else resources + "/runtime-licenses/" + original
            else:
                name = original
            path = _relative(name)
            if platform != "macos" and languages and path.parts[0] == "locales" and path.suffix == ".pak" and path.stem not in languages:
                continue
            if path in entries:
                raise ValueError(f"Duplicate runtime archive path: {path}")
            if path.is_relative_to(resources + "/app") or path.is_relative_to(resources + "/app.asar") or path.is_relative_to(resources + "/app.asar.unpacked"):
                raise ValueError(f"Runtime occupies app destination: {path}")
            entries[path] = info
            if stat.S_ISLNK(info.external_attr >> 16):
                target = source.read(info).decode("utf-8")
                if PurePosixPath(target).is_absolute() or "\\" in target:
                    raise ValueError(f"Invalid runtime symlink: {path}")
                _relative(posixpath.normpath(str(path.parent / target)))
                links[path] = target

        combined = set(entries) | set(occupied)
        if len(combined) != len(entries) + len(occupied):
            raise ValueError("Runtime and app destinations overlap")
        for path in combined:
            if any(parent in combined for parent in path.parents):
                raise ValueError(f"Runtime file/directory collision: {path}")
        if platform == "windows" and len({str(p).casefold() for p in combined}) != len(combined):
            raise ValueError("Case-insensitive Windows destination collision")
        for path, info in sorted(entries.items()):
            if path in links:
                continue
            destination = output / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as content, destination.open("wb") as file:
                shutil.copyfileobj(content, file)
            mode = info.external_attr >> 16
            destination.chmod(0o755 if mode & 0o111 or path.suffix == ".exe" else 0o644)
        for path, target in sorted(links.items()):
            destination = output / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(target)
        for path in links:
            try:
                (output / path).resolve(strict=True).relative_to(output.resolve())
            except (ValueError, RuntimeError, OSError) as error:
                raise ValueError(f"Invalid runtime symlink chain: {path}") from error


def brand_macos(output, executable_name, product_name, app_id, version):
    if not app_id:
        raise ValueError("macOS app_id required")
    plist = output / "Contents/Info.plist"
    metadata = plistlib.loads(plist.read_bytes())
    executable = output / "Contents/MacOS" / metadata["CFBundleExecutable"]
    executable.rename(executable.with_name(executable_name))
    metadata.update(CFBundleExecutable=executable_name, CFBundleName=product_name,
                    CFBundleDisplayName=product_name, CFBundleIdentifier=app_id,
                    CFBundleShortVersionString=version, CFBundleVersion=version)
    plist.write_bytes(plistlib.dumps(metadata, sort_keys=True))
    frameworks = output / "Contents/Frameworks"
    for helper in sorted(frameworks.glob("Electron Helper*.app")):
        suffix = helper.stem.removeprefix("Electron Helper")
        name = product_name + " Helper" + suffix
        helper_plist = helper / "Contents/Info.plist"
        info = plistlib.loads(helper_plist.read_bytes())
        binary = helper / "Contents/MacOS" / info["CFBundleExecutable"]
        binary.rename(binary.with_name(name))
        identifier_suffix = suffix.strip(" ()").lower()
        info.update(CFBundleExecutable=name, CFBundleName=name,
                    CFBundleIdentifier=app_id + ".helper" + ("." + identifier_suffix if identifier_suffix else ""))
        helper_plist.write_bytes(plistlib.dumps(info, sort_keys=True))
        helper.rename(helper.with_name(name + ".app"))


def normalize(output):
    for directory, directories, files in os.walk(output, topdown=False):
        for name in files + [name for name in directories if (Path(directory) / name).is_symlink()]:
            os.utime(os.path.join(directory, name), (0, 0), follow_symlinks=False)
        os.chmod(directory, 0o755)
        os.utime(directory, (0, 0))
