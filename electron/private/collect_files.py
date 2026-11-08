"""Materialize a filtered view of declared source mappings."""

import json
from pathlib import Path
import shutil
import sys

from electron.private.files import expand, normalize, relative_path
from electron.private.matching import select_files


def collect(entries, output, patterns=(), file_matcher=None):
    expanded = list(expand(entries, allow_root=True))
    names = {entry["path"] for entry in expanded}
    selected = select_files(names, patterns, file_matcher) if patterns else names
    files = {}
    for entry in expanded:
        if entry["path"] not in selected:
            continue
        path = relative_path(entry["path"])
        if path in files:
            raise ValueError(f"Duplicate file destination: {path}")
        files[path] = entry
    for path in files:
        if any(parent in files and not files[parent].get("empty_directory") for parent in path.parents):
            raise ValueError(f"File/directory collision: {path}")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for path, entry in sorted(files.items()):
        destination = output / str(path)
        if entry.get("empty_directory"):
            destination.mkdir(parents=True, exist_ok=True)
            continue
        source = Path(entry["source"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o755 if entry.get("executable") or source.stat().st_mode & 0o111 else 0o644)
    normalize(output)
    return sorted(str(path) for path, entry in files.items() if entry.get("empty_directory"))


if __name__ == "__main__":
    options = json.loads(Path(sys.argv[1]).read_text())
    directories = collect(output=sys.argv[2], **options)
    Path(sys.argv[3]).write_text(json.dumps(directories, separators=(",", ":")) + "\n")
