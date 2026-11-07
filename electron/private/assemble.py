"""Assemble a relocatable Linux Electron distribution from declared inputs."""

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys


def relative_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or str(path) != value
            or any(part in (".", "..") for part in path.parts)
            or "\\" in value or ":" in value):
        raise ValueError(f"Expected normalized relative path: {value!r}")
    return path


def assemble(entries, output):
    paths = {}
    for entry in entries:
        path = relative_path(entry["path"])
        if path == PurePosixPath("resources/app.asar"):
            raise ValueError("Runtime app.asar would shadow resources/app")
        if path in paths:
            raise ValueError(f"Duplicate destination: {path}")
        paths[path] = entry
    for path in paths:
        if any(parent in paths for parent in path.parents):
            raise ValueError(f"File/directory collision: {path}")

    package_path = PurePosixPath("resources/app/package.json")
    package = json.loads(Path(paths[package_path]["source"]).read_text())
    main = relative_path(package.get("main", "index.js"))
    if PurePosixPath("resources/app") / main not in paths:
        raise ValueError(f"App entry point missing: {main}")

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for path, entry in sorted(paths.items()):
        source = Path(entry["source"])
        destination = output / str(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        executable = entry.get("executable", False) or bool(source.stat().st_mode & 0o111)
        destination.chmod(0o755 if executable else 0o644)
        os.utime(destination, (0, 0))
    for directory, _, _ in os.walk(output, topdown=False):
        Path(directory).chmod(0o755)
        os.utime(directory, (0, 0))


if __name__ == "__main__":
    assemble(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2])
