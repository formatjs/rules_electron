"""Extract declared distribution ZIPs without following archive symlinks."""

from pathlib import Path, PurePosixPath
import plistlib
import posixpath
import re
import shutil
import stat
from zipfile import ZipFile

from electron.private.files import normalize


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
        directories = {path for path, entry in occupied.items() if entry.get("empty_directory")} if isinstance(occupied, dict) else set()
        checked_directories = {PurePosixPath(str(path).casefold()) for path in directories} if platform == "windows" else directories
        checked = {PurePosixPath(str(path).casefold()) for path in combined} if platform == "windows" else combined
        for path in checked:
            if any(parent in checked and parent not in checked_directories for parent in path.parents):
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


def _macos_url_types(protocols, roles):
    protocols = {} if protocols is None else protocols
    roles = {} if roles is None else roles
    if not isinstance(protocols, dict) or not isinstance(roles, dict) or set(roles) - set(protocols):
        raise ValueError("Invalid macOS protocol mapping or unmatched role")
    result, seen = [], set()
    for name, schemes in sorted(protocols.items()):
        if not isinstance(name, str) or not name.strip() or any(ord(c) < 32 for c in name):
            raise ValueError("Invalid macOS protocol name")
        role = roles.get(name, "Editor")
        if not isinstance(role, str) or role not in {"Editor", "Viewer", "Shell", "QLGenerator", "None"}:
            raise ValueError("Invalid macOS protocol role")
        if not isinstance(schemes, (list, tuple)) or not schemes:
            raise ValueError("macOS protocol needs at least one scheme")
        normalized = []
        for scheme in schemes:
            if not isinstance(scheme, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", scheme):
                raise ValueError("Invalid macOS protocol scheme")
            scheme = scheme.lower()
            if scheme in seen:
                raise ValueError("Duplicate macOS protocol scheme")
            seen.add(scheme)
            normalized.append(scheme)
        result.append({"CFBundleURLName": name, "CFBundleURLSchemes": sorted(normalized), "CFBundleTypeRole": role})
    return result


def brand_macos(output, executable_name, product_name, app_id, version, asar_header_hash=None, build_version="",
                protocols=None, protocol_roles=None, extra_asar_hashes=None, icon_name=None):
    if not app_id:
        raise ValueError("macOS app_id required")
    url_types = _macos_url_types(protocols, protocol_roles)
    plist = output / "Contents/Info.plist"
    metadata = plistlib.loads(plist.read_bytes())
    executable = output / "Contents/MacOS" / metadata["CFBundleExecutable"]
    destination = executable.with_name(executable_name)
    if destination != executable and destination.exists():
        raise ValueError(f"Executable destination already occupied: {executable_name}")
    executable.rename(destination)
    metadata.update(CFBundleExecutable=executable_name, CFBundleName=product_name,
                    CFBundleDisplayName=product_name, CFBundleIdentifier=app_id,
                    CFBundleShortVersionString=version, CFBundleVersion=build_version or version)
    if icon_name:
        metadata["CFBundleIconFile"] = icon_name
        metadata.pop("CFBundleIconName", None)
    if url_types:
        metadata["CFBundleURLTypes"] = url_types
    metadata.pop("ElectronAsarIntegrity", None)
    integrities = dict(extra_asar_hashes or {})
    if asar_header_hash:
        integrities["Resources/app.asar"] = asar_header_hash
    if integrities:
        metadata["ElectronAsarIntegrity"] = {
            path: {"algorithm": "SHA256", "hash": digest} for path, digest in sorted(integrities.items())
        }
    plist.write_bytes(plistlib.dumps(metadata, sort_keys=True))
    frameworks = output / "Contents/Frameworks"
    for helper in sorted(frameworks.glob("Electron Helper*.app")):
        suffix = helper.stem.removeprefix("Electron Helper")
        name = product_name + " Helper" + suffix
        helper_plist = helper / "Contents/Info.plist"
        info = plistlib.loads(helper_plist.read_bytes())
        binary = helper / "Contents/MacOS" / info.get("CFBundleExecutable", helper.stem)
        binary.rename(binary.with_name(name))
        identifier_suffix = suffix.strip(" ()").lower()
        info.update(CFBundleExecutable=name, CFBundleName=name,
                    CFBundleIdentifier=app_id + ".helper" + ("." + identifier_suffix if identifier_suffix else ""),
                    CFBundleShortVersionString=version, CFBundleVersion=build_version or version)
        if icon_name:
            resources = helper / "Contents/Resources"
            resources.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output / "Contents/Resources" / icon_name, resources / icon_name)
            (resources / icon_name).chmod(0o644)
            info["CFBundleIconFile"] = icon_name
            info.pop("CFBundleIconName", None)
        helper_plist.write_bytes(plistlib.dumps(info, sort_keys=True))
        helper.rename(helper.with_name(name + ".app"))
