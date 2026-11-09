"""Declared file mappings shared by app and ASAR assembly."""

import os
import json
from pathlib import Path, PurePosixPath


def relative_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or str(path) != value
            or any(part in (".", "..") for part in path.parts)
            or "\\" in value or ":" in value or "\0" in value):
        raise ValueError(f"Expected normalized relative path: {value!r}")
    return path

def read_directories(manifest):
    declared = json.loads(Path(manifest).read_text())
    if not isinstance(declared, list) or any(not isinstance(path, str) for path in declared):
        raise ValueError("Expected directory path list")
    return {relative_path(path) for path in declared}


def read_symlinks(manifest):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate symlink path")
            result[key] = value
        return result
    declared = json.loads(Path(manifest).read_text(), object_pairs_hook=unique)
    if not isinstance(declared, dict):
        raise ValueError("Expected symlink path mapping")
    for path, target in declared.items():
        relative_path(path)
        if not isinstance(target, str):
            raise ValueError("Expected symlink target string")
        if target:
            relative_path(target)
    return declared


def _walk_error(error):
    raise error


def expand(entries, *, allow_root=False):
    for entry in entries:
        destination = (PurePosixPath(".") if allow_root and entry.get("directory", False) and entry["path"] == ""
                       else relative_path(entry["path"]))
        if not entry.get("directory", False):
            if entry.get("symlink_manifest"):
                raise ValueError("Symlink metadata requires input tree")
            yield entry
            continue
        source = Path(entry["source"])
        if not source.is_dir():
            raise ValueError(f"Expected input tree: {source}")
        if entry.get("symlink_manifest"):
            for path, target in sorted(read_symlinks(entry["symlink_manifest"]).items()):
                mapped = destination / target if target else destination
                yield {"path": str(destination / path), "symlink_target": "" if mapped == PurePosixPath(".") else str(mapped)}
        empty = set()
        if entry.get("directory_manifest"):
            empty.update(str(path) for path in read_directories(entry["directory_manifest"]))
        for directory, directories, files in os.walk(source, followlinks=False, onerror=_walk_error):
            for name in directories:
                if (Path(directory) / name).is_symlink():
                    raise ValueError("Directory symlinks inside input trees are not supported")
            if not directories and not files:
                empty.add(Path(directory).relative_to(source).as_posix())
            for name in files:
                file = Path(directory) / name
                # Bazel's sandbox projects declared tree files as symlink leaves.
                relative = file.relative_to(source).as_posix()
                relative_path(relative)
                if not file.is_file():
                    raise ValueError(f"Expected regular tree file: {relative}")
                yield {"source": str(file), "path": str(destination / relative), "executable": False}
        for path in sorted(empty):
            path = destination / path
            if path != PurePosixPath("."):
                yield {"path": str(path), "empty_directory": True}


def normalize(output):
    for directory, directories, files in os.walk(output, topdown=False):
        for name in files + [name for name in directories if (Path(directory) / name).is_symlink()]:
            os.utime(os.path.join(directory, name), (0, 0), follow_symlinks=False)
        os.chmod(directory, 0o755)
        os.utime(directory, (0, 0))
