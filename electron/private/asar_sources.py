"""Create a standalone ASAR and its declared unpacked tree and header digest."""

import json
import os
from pathlib import Path
import sys

from electron.private.asar import create_archive
from electron.private.files import expand, normalize, relative_path


def write_sources(entries, archive, unpacked=(), symlinks=None):
    files = {}
    for entry in expand(entries):
        path = relative_path(entry["path"])
        if path in files:
            raise ValueError(f"Duplicate ASAR destination: {path}")
        files[path] = Path(entry["source"])
    for path in files:
        if any(parent in files for parent in path.parents):
            raise ValueError(f"ASAR file/directory collision: {path}")
    for path in unpacked:
        relative_path(path)
    sidecar = Path(str(archive) + ".unpacked")
    digest = create_archive({str(path): source for path, source in files.items()}, archive, unpacked, symlinks)
    sidecar.mkdir(parents=True, exist_ok=True)
    Path(archive).chmod(0o644)
    os.utime(archive, (0, 0))
    normalize(sidecar)
    return digest


if __name__ == "__main__":
    manifest, archive, sidecar, digest = sys.argv[1:]
    if Path(sidecar) != Path(archive + ".unpacked"):
        raise ValueError("ASAR sidecar must follow its archive")
    options = json.loads(Path(manifest).read_text())
    Path(digest).write_text(write_sources(options["entries"], archive, options["unpacked"], options.get("symlinks")) + "\n")
