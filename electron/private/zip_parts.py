"""Keep compressed ZIP bytes in bounded CAS blobs; assemble without recompression."""

import json
from pathlib import Path
import shutil
import sys
import tempfile

from electron.private.archive import Entry, inventory, relative, validate, write_zip


def compress(sources, platform, compression_level, output, part_size=64 * 1024**2):
    if platform not in ("linux", "macos", "windows") or not 0 <= compression_level <= 9 or part_size <= 0:
        raise ValueError("Invalid ZIP settings")
    entries = {}
    for source in sources:
        path, prefix = Path(source["source"]), relative(source["prefix"])
        if source["directory"]:
            with inventory(path, platform, declared_tree=True) as (children, _):
                additions = {prefix: Entry("directory", 0o755)}
                additions.update({prefix + "/" + name: entry for name, entry in children.items()})
        else:
            metadata = path.stat()
            additions = {prefix: Entry("file", 0o755 if metadata.st_mode & 0o111 else 0o644, metadata.st_size, path)}
        for name, entry in additions.items():
            if name in entries and (entry.kind != "directory" or entries[name].kind != "directory"):
                raise ValueError("Duplicate ZIP path: " + name)
            entries[name] = entry
    validate(entries, platform)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        archive = Path(work) / "archive.zip"
        write_zip(sorted(entries.items()), lambda entry: entry.source.open("rb"), archive, compression_level)
        count = 0
        with archive.open("rb") as content:
            while block := content.read(part_size):
                (output / f"{count:08d}").write_bytes(block)
                count += 1
        (output / "index.json").write_text(json.dumps({"parts": count, "size": archive.stat().st_size}) + "\n")


def assemble(source, output):
    source = Path(source)
    index = json.loads((source / "index.json").read_text())
    count, expected = index["parts"], index["size"]
    if type(count) is not int or not 0 < count <= 100000 or type(expected) is not int or expected <= 0:
        raise ValueError("Invalid ZIP part index")
    if {path.name for path in source.iterdir()} != {"index.json"} | {f"{i:08d}" for i in range(count)}:
        raise ValueError("ZIP parts missing or unexpected")
    total = 0
    with Path(output).open("wb") as destination:
        for i in range(count):
            part = source / f"{i:08d}"
            total += part.stat().st_size
            with part.open("rb") as content:
                shutil.copyfileobj(content, destination, 1024**2)
    if total != expected:
        raise ValueError("ZIP parts truncated")


if __name__ == "__main__":
    if sys.argv[1] == "compress":
        compress(output=sys.argv[3], **json.loads(Path(sys.argv[2]).read_text()))
    elif sys.argv[1] == "assemble":
        assemble(sys.argv[2], sys.argv[3])
    else:
        raise ValueError("Expected compress or assemble")
