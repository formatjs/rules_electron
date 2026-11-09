"""Assemble a relocatable Linux Electron distribution from declared inputs."""

import json
import posixpath
from pathlib import Path, PurePosixPath
import shutil
import subprocess

from electron.private.asar import create_archive, header_hash as archive_header_hash
from electron.private.asar_paths import ArchivePaths
from electron.private.files import expand as _expand, relative_path
from electron.private.fuses import set_fuses
from electron.private.identity import build_identity
from electron.private.icons import validate_icns, validate_ico
from electron.private.matching import select_files
from electron.private.runtime import brand_macos, extract_runtime, normalize


def assemble(entries, output, asar=False, asar_unpacked=(), fuses=None,
             executable_name="electron", remove_package_scripts=False,
             platform="linux", runtime_archive="", exclude_files=(),
             product_name="Electron", app_id="", runtime_languages=(),
             windows_resource_tool=None, windows_metadata=None,
             build_version="", build_number="", macos_protocols=None, macos_protocol_roles=None,
             extra_files=(), extra_asars=(), macos_icon="", windows_icon="", asar_symlinks=None,
             asar_unpacked_patterns=(), file_matcher=None, macos_extra_plist="", resource_symlinks=None):
    if platform not in ("linux", "macos", "windows"):
        raise ValueError(f"Unsupported platform: {platform}")
    if platform == "windows" and resource_symlinks:
        raise ValueError("Resource symlinks currently require Linux or macOS")
    if macos_extra_plist and platform != "macos":
        raise ValueError("macos_extra_plist requires a macOS target")
    if platform != "macos" and (macos_protocols or macos_protocol_roles):
        raise ValueError("macOS protocols require a macOS target")
    if macos_icon:
        if platform != "macos":
            raise ValueError("macos_icon requires a macOS target")
        validate_icns(macos_icon)
    embedded_integrity = (fuses or {}).get("enableEmbeddedAsarIntegrityValidation") == "on"
    if embedded_integrity and (not asar or platform == "linux" or platform == "windows" and not windows_resource_tool):
        raise ValueError("enableEmbeddedAsarIntegrityValidation requires ASAR and macOS or a Windows resource tool")
    if platform != "windows" and (windows_resource_tool or windows_metadata or windows_icon):
        raise ValueError("Windows resource options require a Windows target")
    if platform == "windows" and (build_version or build_number) and not windows_resource_tool:
        raise ValueError("Windows build identity requires windows_resource_tool")
    if windows_metadata and not windows_resource_tool:
        raise ValueError("windows_metadata requires windows_resource_tool")
    if windows_icon and not windows_resource_tool:
        raise ValueError("windows_icon requires windows_resource_tool")
    if windows_icon:
        validate_ico(windows_icon)
    resources = "Contents/Resources" if platform == "macos" else "resources"
    if not asar and asar_unpacked:
        raise ValueError("asar_unpacked requires asar=True")
    if not asar and asar_unpacked_patterns:
        raise ValueError("asar_unpacked_patterns requires asar=True")
    if not asar and asar_symlinks:
        raise ValueError("asar_symlinks requires asar=True")
    if not asar and (fuses or {}).get("onlyLoadAppFromAsar") == "on":
        raise ValueError("onlyLoadAppFromAsar requires asar=True")
    expanded = list(_expand(entries))
    if macos_icon:
        expanded.append({"source": macos_icon, "path": "Contents/Resources/app.icns"})
    extra_hashes = {}
    for archive in extra_asars:
        name = relative_path(archive["path"])
        checked = str(name).casefold() if platform == "windows" else str(name)
        if not str(name).endswith(".asar") or checked.split("/")[0] in ("app", "app.asar", "app.asar.unpacked"):
            raise ValueError(f"Invalid additional ASAR destination: {name}")
        digest = Path(archive["header_hash"]).read_text().strip()
        if archive_header_hash(archive["archive"]) != digest:
            raise ValueError("Additional ASAR header digest mismatch")
        destination = resources + "/" + str(name)
        expanded.append({"source": archive["archive"], "path": destination})
        expanded.extend(_expand([{"source": archive["unpacked"], "path": destination + ".unpacked", "directory": True}]))
        extra_hashes[destination.removeprefix("Contents/")] = digest
    for entry in _expand(extra_files):
        path = relative_path(("Contents/" if platform == "macos" else "") + entry["path"])
        checked = PurePosixPath(str(path).casefold()) if platform == "windows" else path
        if any(checked.is_relative_to(resources + "/" + name) for name in ("app", "app.asar", "app.asar.unpacked")):
            raise ValueError(f"Extra file occupies app destination: {path}")
        if "symlink_target" in entry:
            target = relative_path(("Contents/" if platform == "macos" else "") + entry["symlink_target"])
            expanded.append(dict(entry, path=str(path), symlink_target=str(target), extra_file_link=True))
        else:
            expanded.append(dict(entry, path=str(path)))
    paths = {}
    asar_symlinks = dict(asar_symlinks or {})
    resource_symlinks = dict(resource_symlinks or {})
    extra_symlinks = {}
    app_prefix = PurePosixPath(resources + "/app")
    resource_root = PurePosixPath(resources)
    for entry in expanded:
        path = relative_path(entry["path"])
        if "symlink_target" in entry:
            target = relative_path(entry["symlink_target"])
            if entry.get("extra_file_link"):
                if platform == "windows":
                    raise ValueError("Filesystem symlinks currently require Linux or macOS")
                if path in extra_symlinks:
                    raise ValueError(f"Duplicate generated link: {path}")
                extra_symlinks[path] = target
                continue
            if path.is_relative_to(app_prefix):
                if not asar and platform == "windows":
                    raise ValueError("Filesystem symlinks currently require Linux or macOS")
                if not target.is_relative_to(app_prefix):
                    raise ValueError("Generated ASAR link escapes app")
                links, prefix = asar_symlinks, app_prefix
            elif path.is_relative_to(resource_root) and target.is_relative_to(resource_root):
                if platform == "windows":
                    raise ValueError("Resource symlinks currently require Linux or macOS")
                links, prefix = resource_symlinks, resource_root
            else:
                raise ValueError("Generated link escapes resources")
            alias = str(path.relative_to(prefix))
            if alias in links:
                raise ValueError(f"Duplicate generated link: {alias}")
            relative = target.relative_to(prefix)
            links[alias] = "" if relative == PurePosixPath(".") else str(relative)
            continue
        if path.is_relative_to(resources + "/app.asar") or path.is_relative_to(resources + "/app.asar.unpacked"):
            raise ValueError("Runtime app.asar would shadow resources/app")
        if path in paths:
            raise ValueError(f"Duplicate destination: {path}")
        paths[path] = entry
    if resource_symlinks:
        resource_root = PurePosixPath(resources)
        resource_files = {str(path.relative_to(resource_root)): entry for path, entry in paths.items() if path != resource_root and path.is_relative_to(resource_root)}
        for alias, target in resource_symlinks.items():
            relative_path(alias)
            if not isinstance(target, str):
                raise ValueError("Resource link target must be a string")
            if target:
                relative_path(target)
            if any(name.split("/")[0] in ("app", "app.asar", "app.asar.unpacked") for name in (alias, target) if name):
                raise ValueError("Resource link occupies app destination")
        namespace = ArchivePaths({name for name, entry in resource_files.items() if not entry.get("empty_directory")},
                                 resource_symlinks, {name for name, entry in resource_files.items() if entry.get("empty_directory")})
        if any(target.split("/")[0] in ("app", "app.asar", "app.asar.unpacked") for target in namespace.links.values()):
            raise ValueError("Resource link occupies app destination")
        for alias, target in resource_symlinks.items():
            path = resource_root / alias
            paths[path] = {"symlink": posixpath.relpath(str(resource_root / target), str(path.parent))}
    filesystem_links = dict(extra_symlinks)
    if not asar:
        filesystem_links.update({app_prefix / alias: app_prefix / target for alias, target in asar_symlinks.items()})
    if filesystem_links:
        for path in filesystem_links:
            if path in paths:
                raise ValueError(f"Link/file collision: {path}")
        existing_links = {str(path): posixpath.normpath(str(path.parent / entry["symlink"]))
                          for path, entry in paths.items() if "symlink" in entry}
        namespace = ArchivePaths({str(path) for path, entry in paths.items() if not entry.get("empty_directory") and "symlink" not in entry},
                                 {**existing_links, **{str(path): str(target) for path, target in filesystem_links.items()}},
                                 {str(path) for path, entry in paths.items() if entry.get("empty_directory")})
        for path in extra_symlinks:
            target = PurePosixPath(namespace.links[str(path)])
            if any(target.is_relative_to(resource_root / name) for name in ("app", "app.asar", "app.asar.unpacked")):
                raise ValueError("Extra file link targets app destination")
        for path, target in filesystem_links.items():
            paths[path] = {"symlink": posixpath.relpath(str(target), str(path.parent))}
    checked_paths = {PurePosixPath(str(path).casefold()): entry for path, entry in paths.items()} if platform in ("windows", "macos") else paths
    if len(checked_paths) != len(paths):
        raise ValueError("Case-insensitive destination collision")
    for path in checked_paths:
        if any(parent in checked_paths and not checked_paths[parent].get("empty_directory") for parent in path.parents):
            raise ValueError(f"File/directory collision: {path}")

    package_path = PurePosixPath(resources + "/app/package.json")
    package = json.loads(Path(paths[package_path]["source"]).read_text())
    native_version = build_identity(package.get("version"), build_version, build_number, platform) if (build_version or build_number) else package.get("version", "")
    app_prefix = PurePosixPath(resources + "/app")
    app_files = {str(path.relative_to(app_prefix)): path for path, value in paths.items() if path.is_relative_to(app_prefix) and not value.get("empty_directory") and "symlink" not in value}
    app_directories = {str(path.relative_to(app_prefix)) for path, value in paths.items() if path != app_prefix and path.is_relative_to(app_prefix) and value.get("empty_directory")}
    main = relative_path(package.get("main", "index.js"))
    index = ArchivePaths(app_files, asar_symlinks, app_directories)
    try:
        entry = index.resolve(str(main))
    except ValueError:
        entry = None
    if entry not in app_files:
        raise ValueError(f"App entry point missing: {main}")
    for name in asar_unpacked:
        relative_path(name)
        if name not in app_files:
            raise ValueError(f"ASAR unpacked path not declared: {name}")
    asar_unpacked = sorted(set(asar_unpacked) | select_files(app_files, asar_unpacked_patterns, file_matcher))

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if runtime_archive:
        extract_runtime(runtime_archive, output, platform, exclude_files, paths, runtime_languages)
    for path, entry in sorted(paths.items()):
        destination = output / str(path)
        if entry.get("empty_directory"):
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if "symlink" in entry:
            continue
        source = Path(entry["source"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        executable = entry.get("executable", False) or bool(source.stat().st_mode & 0o111)
        destination.chmod(0o755 if executable else 0o644)
    for path, entry in sorted(paths.items()):
        if "symlink" in entry:
            destination = output / str(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(entry["symlink"])
    if remove_package_scripts:
        package.pop("scripts", None)
        (output / package_path).write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        (output / package_path).chmod(0o644)
    header_hash = None
    if asar:
        archive = output / resources / "app.asar"
        header_hash = create_archive({name: output / path for name, path in app_files.items()}, archive, asar_unpacked, asar_symlinks, app_directories)
        archive.chmod(0o644)
        shutil.rmtree(output / app_prefix)
    if platform == "macos":
        brand_macos(output, executable_name, product_name, app_id, package["version"], header_hash,
                    build_version=native_version, protocols=macos_protocols, protocol_roles=macos_protocol_roles,
                    extra_asar_hashes=extra_hashes, icon_name="app.icns" if macos_icon else None,
                    extra_plist=macos_extra_plist)
        binary = output / "Contents/Frameworks/Electron Framework.framework/Electron Framework"
    else:
        original = "electron.exe" if platform == "windows" else "electron"
        name = executable_name + (".exe" if platform == "windows" and not executable_name.endswith(".exe") else "")
        binary = output / name
        if original != name:
            occupied = (any(path.name != original and path.name.casefold() == name.casefold()
                            for path in output.iterdir()) if platform == "windows" else binary.exists())
            if occupied:
                raise ValueError(f"Executable destination already occupied: {name}")
            (output / original).rename(binary)
    if windows_resource_tool:
        subprocess.run([
            windows_resource_tool["node"], windows_resource_tool["script"],
            windows_resource_tool["modules"], str(binary), json.dumps({
                "version": package["version"], "build_version": native_version, "product_name": product_name,
                "executable_name": executable_name, "header_hash": header_hash,
                "extra_asar_hashes": extra_hashes,
                "metadata": windows_metadata or {},
                "icon": str(windows_icon) if windows_icon else "",
            }),
        ], check=True)
    if fuses:
        set_fuses(binary, fuses)
    normalize(output)
