"""Assemble a relocatable Linux Electron distribution from declared inputs."""

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

from electron.private.asar import create_archive
from electron.private.fuses import set_fuses
from electron.private.runtime import brand_macos, extract_runtime, normalize


def relative_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or str(path) != value
            or any(part in (".", "..") for part in path.parts)
            or "\\" in value or ":" in value):
        raise ValueError(f"Expected normalized relative path: {value!r}")
    return path


def _walk_error(error):
    raise error


def _expand(entries):
    for entry in entries:
        destination = relative_path(entry["path"])
        if not entry.get("directory", False):
            yield entry
            continue
        source = Path(entry["source"])
        if not source.is_dir():
            raise ValueError(f"Expected input tree: {source}")
        for directory, directories, files in os.walk(source, followlinks=False, onerror=_walk_error):
            for name in directories:
                if (Path(directory) / name).is_symlink():
                    raise ValueError("Directory symlinks inside input trees are not supported")
            for name in files:
                file = Path(directory) / name
                # Bazel's sandbox projects declared tree files as symlink leaves.
                relative = file.relative_to(source).as_posix()
                relative_path(relative)
                if not file.is_file():
                    raise ValueError(f"Expected regular tree file: {relative}")
                yield {"source": str(file), "path": str(destination / relative), "executable": False}


def assemble(entries, output, asar=False, asar_unpacked=(), fuses=None,
             executable_name="electron", remove_package_scripts=False,
             platform="linux", runtime_archive="", exclude_files=(),
             product_name="Electron", app_id="", runtime_languages=(),
             windows_resource_tool=None, windows_metadata=None):
    if platform not in ("linux", "macos", "windows"):
        raise ValueError(f"Unsupported platform: {platform}")
    embedded_integrity = (fuses or {}).get("enableEmbeddedAsarIntegrityValidation") == "on"
    if embedded_integrity and (not asar or platform == "linux" or platform == "windows" and not windows_resource_tool):
        raise ValueError("enableEmbeddedAsarIntegrityValidation requires ASAR and macOS or a Windows resource tool")
    if platform != "windows" and (windows_resource_tool or windows_metadata):
        raise ValueError("Windows resource options require a Windows target")
    if windows_metadata and not windows_resource_tool:
        raise ValueError("windows_metadata requires windows_resource_tool")
    resources = "Contents/Resources" if platform == "macos" else "resources"
    if not asar and asar_unpacked:
        raise ValueError("asar_unpacked requires asar=True")
    if not asar and (fuses or {}).get("onlyLoadAppFromAsar") == "on":
        raise ValueError("onlyLoadAppFromAsar requires asar=True")
    paths = {}
    for entry in _expand(entries):
        path = relative_path(entry["path"])
        if path.is_relative_to(resources + "/app.asar") or path.is_relative_to(resources + "/app.asar.unpacked"):
            raise ValueError("Runtime app.asar would shadow resources/app")
        if path in paths:
            raise ValueError(f"Duplicate destination: {path}")
        paths[path] = entry
    for path in paths:
        if any(parent in paths for parent in path.parents):
            raise ValueError(f"File/directory collision: {path}")

    package_path = PurePosixPath(resources + "/app/package.json")
    package = json.loads(Path(paths[package_path]["source"]).read_text())
    main = relative_path(package.get("main", "index.js"))
    if PurePosixPath(resources + "/app") / main not in paths:
        raise ValueError(f"App entry point missing: {main}")

    app_prefix = PurePosixPath(resources + "/app")
    app_files = {str(path.relative_to(app_prefix)): path for path in paths if path.is_relative_to(app_prefix)}
    for name in asar_unpacked:
        relative_path(name)
        if name not in app_files:
            raise ValueError(f"ASAR unpacked path not declared: {name}")

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if runtime_archive:
        extract_runtime(runtime_archive, output, platform, exclude_files, paths, runtime_languages)
    for path, entry in sorted(paths.items()):
        source = Path(entry["source"])
        destination = output / str(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        executable = entry.get("executable", False) or bool(source.stat().st_mode & 0o111)
        destination.chmod(0o755 if executable else 0o644)
    if remove_package_scripts:
        package.pop("scripts", None)
        (output / package_path).write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        (output / package_path).chmod(0o644)
    header_hash = None
    if asar:
        archive = output / resources / "app.asar"
        header_hash = create_archive({name: output / path for name, path in app_files.items()}, archive, asar_unpacked)
        archive.chmod(0o644)
        shutil.rmtree(output / app_prefix)
    if platform == "macos":
        brand_macos(output, executable_name, product_name, app_id, package["version"], header_hash)
        binary = output / "Contents/Frameworks/Electron Framework.framework/Electron Framework"
    else:
        original = "electron.exe" if platform == "windows" else "electron"
        name = executable_name + (".exe" if platform == "windows" and not executable_name.endswith(".exe") else "")
        binary = output / name
        if original != name:
            if binary.exists():
                raise ValueError(f"Executable destination already occupied: {name}")
            (output / original).rename(binary)
    if windows_resource_tool:
        subprocess.run([
            windows_resource_tool["node"], windows_resource_tool["script"],
            windows_resource_tool["modules"], str(binary), json.dumps({
                "version": package["version"], "product_name": product_name,
                "executable_name": executable_name, "header_hash": header_hash,
                "metadata": windows_metadata or {},
            }),
        ], check=True)
    if fuses:
        set_fuses(binary, fuses)
    normalize(output)
