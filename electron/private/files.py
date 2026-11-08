"""Declared file mappings shared by app and ASAR assembly."""

import os
from pathlib import Path, PurePosixPath


def relative_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or str(path) != value
            or any(part in (".", "..") for part in path.parts)
            or "\\" in value or ":" in value):
        raise ValueError(f"Expected normalized relative path: {value!r}")
    return path


def _walk_error(error):
    raise error


def expand(entries, *, allow_root=False):
    for entry in entries:
        destination = (PurePosixPath(".") if allow_root and entry.get("directory", False) and entry["path"] == ""
                       else relative_path(entry["path"]))
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


def normalize(output):
    for directory, directories, files in os.walk(output, topdown=False):
        for name in files + [name for name in directories if (Path(directory) / name).is_symlink()]:
            os.utime(os.path.join(directory, name), (0, 0), follow_symlinks=False)
        os.chmod(directory, 0o755)
        os.utime(directory, (0, 0))
