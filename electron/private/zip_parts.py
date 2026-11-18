"""Keep compressed ZIP bytes in bounded CAS blobs; assemble without recompression."""

import copy
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zipfile
from zipfile import ZipFile, ZipInfo

from electron.private.archive import Entry, inventory, relative, split_archive, validate, write_zip


def source_entries(sources, platform):
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
    return entries


def compress(sources, platform, compression_level, output, part_size=64 * 1024**2):
    if platform not in ("linux", "macos", "windows") or not 0 <= compression_level <= 9 or part_size <= 0:
        raise ValueError("Invalid ZIP settings")
    entries = source_entries(sources, platform)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        archive = Path(work) / "archive.zip"
        write_zip(sorted(entries.items()), lambda entry: entry.source.open("rb"), archive, compression_level)
        split_archive(archive, output, part_size)


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


def layout(sources, platform, output):
    entries = source_entries(sources, platform)
    Path(output).write_text(json.dumps({name: {"kind": entry.kind, "mode": entry.mode, "target": entry.target}
                                       for name, entry in sorted(entries.items())}) + "\n")


def member(sources, output, compression_level):
    entries = source_entries(sources, "windows")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    write_zip(sorted(entries.items()), lambda entry: entry.source.open("rb"), output, compression_level)
    if Path(output).stat().st_size > 240 * 1024**2:
        raise ValueError("ZIP member batch exceeds 240MiB; disable incremental ZIP mode")


def merge(parts, layout_file, output):
    expected = json.loads(Path(layout_file).read_text())
    members = {}
    for path in sorted(Path(parts).rglob("*.zip")):
        with ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.filename in members:
                    raise ValueError("Duplicate ZIP member: " + info.filename)
                members[info.filename] = (path, info)
    if set(members) != {name for name, entry in expected.items() if entry["kind"] != "directory"}:
        raise ValueError("ZIP members do not match layout")
    with ZipFile(output, "w") as archive:
        for name, entry in expected.items():
            if entry["kind"] == "directory":
                info = ZipInfo(name + "/", (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = ((0o040000 | entry["mode"]) << 16) | 0x10
                archive.writestr(info, b"")
                continue
            source, original = members[name]
            info = copy.copy(original)
            info.extra = b""
            info.flag_bits &= ~8
            info.header_offset = archive.fp.tell()
            with source.open("rb") as content:
                content.seek(original.header_offset)
                header = content.read(30)
                if len(header) != 30 or header[:4] != b"PK\x03\x04":
                    raise ValueError("Invalid ZIP member header")
                filename_size, extra_size = struct.unpack_from("<HH", header, 26)
                content.seek(filename_size + extra_size, 1)
                # zipfile exposes no public interface for precompressed members.
                archive.fp.write(info.FileHeader(info.file_size > zipfile.ZIP64_LIMIT or info.compress_size > zipfile.ZIP64_LIMIT))
                remaining = info.compress_size
                while remaining:
                    block = content.read(min(remaining, 1024**2))
                    if not block:
                        raise ValueError("Truncated compressed ZIP member")
                    archive.fp.write(block)
                    remaining -= len(block)
            archive.filelist.append(info)
            archive.NameToInfo[info.filename] = info
            archive.start_dir = archive.fp.tell()
            archive._didModify = True


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1].startswith("@"):
        sys.argv[1:] = Path(sys.argv[1][1:]).read_text().splitlines()
    if sys.argv[1] == "layout":
        config = json.loads(Path(sys.argv[2]).read_text())
        layout(config["sources"], config["platform"], sys.argv[3])
    elif sys.argv[1] == "member":
        member(json.loads(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
    elif sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3], sys.argv[4])
    elif sys.argv[1] == "compress":
        compress(output=sys.argv[3], **json.loads(Path(sys.argv[2]).read_text()))
    elif sys.argv[1] == "assemble":
        assemble(sys.argv[2], sys.argv[3])
    else:
        raise ValueError("Expected compress or assemble")
