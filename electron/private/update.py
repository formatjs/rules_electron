"""Deterministic electron-updater feed metadata and external v2 blockmaps."""

import base64
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import struct
import zlib
from urllib.parse import quote

_CHUNK_MIN = 16 * 1024
_CHUNK_MAX = 64 * 1024
_GEAR = tuple(int.from_bytes(hashlib.sha256(b"rules_electron/blockmap/v1/" + bytes([i])).digest()[:4], "little") for i in range(256))


def _content_chunks(reader):
    data = reader.read(_CHUNK_MAX)
    while data:
        boundary = len(data)
        state = 0
        # A 32-bit gear state forgets earlier bytes after 32 shifts.
        for index in range(min(_CHUNK_MIN - 32, len(data)), len(data)):
            state = ((state << 1) + _GEAR[data[index]]) & 0xFFFFFFFF
            if index + 1 >= _CHUNK_MIN and state & 0x3FFF == 0:
                boundary = index + 1
                break
        yield data[:boundary]
        tail = data[boundary:]
        data = tail + reader.read(_CHUNK_MAX - len(tail))


def channel_filename(platform, architecture, channel):
    if platform not in ("linux", "macos", "windows") or architecture not in ("x64", "arm64"):
        raise ValueError("Unsupported update platform or architecture")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", channel):
        raise ValueError("Invalid update channel")
    suffix = {"windows": "", "macos": "-mac", "linux": "-linux"}[platform]
    if platform == "linux" and architecture != "x64":
        suffix += "-" + architecture
    return channel + suffix + ".yml"


def _filename(name):
    if (not name or name in (".", "..") or name.endswith((".", " "))
            or any(c in name for c in '/\\:<>"|?*')
            or any(ord(c) < 32 for c in name)
            or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}):
        raise ValueError(f"Invalid published filename: {name!r}")
    return name


def _version(value):
    number = r"(?:0|[1-9][0-9]*)"
    identifier = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][A-Za-z0-9-]*)"
    pattern = rf"{number}\.{number}\.{number}(?:-{identifier}(?:\.{identifier})*)?(?:\+[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)?"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("App version must be a valid SemVer")
    return value


def embedded_blockmap_size(path):
    path = Path(path)
    length = path.stat().st_size
    if length < 5:
        raise ValueError("AppImage embedded blockmap missing")
    with path.open("rb") as source:
        source.seek(-4, 2)
        size = struct.unpack(">I", source.read(4))[0]
        if not 0 < size <= min(length - 4, 64 * 1024**2):
            raise ValueError("Invalid AppImage blockmap trailer")
        source.seek(-4 - size, 2)
        compressed = source.read(size)
    decoder = zlib.decompressobj(wbits=-15)
    data = decoder.decompress(compressed, 64 * 1024**2 + 1)
    if len(data) > 64 * 1024**2 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Invalid AppImage embedded blockmap stream")
    blockmap = json.loads(data)
    files = blockmap.get("files", [])
    if blockmap.get("version") != "2" or len(files) != 1 or files[0].get("offset") != 0:
        raise ValueError("Unsupported AppImage blockmap layout")
    sizes, checksums = files[0].get("sizes", []), files[0].get("checksums", [])
    if (not sizes or len(sizes) != len(checksums)
            or any(type(value) is not int or value <= 0 for value in sizes)
            or sum(sizes) != length - size - 4):
        raise ValueError("AppImage blockmap coverage mismatch")
    for checksum in checksums:
        if not isinstance(checksum, str) or not 0 < len(base64.b64decode(checksum, validate=True)) <= 64:
            raise ValueError("Invalid AppImage block checksum")
    return size


def create_feed(artifacts, package_json, output, platform, architecture,
                release_date, channel="latest", release_notes="",
                staging_percentage=-1, blockmaps=(), embedded_blockmaps=()):
    metadata_name = channel_filename(platform, architecture, channel)
    version = _version(json.loads(Path(package_json).read_text(encoding="utf-8")).get("version"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", release_date):
        raise ValueError("release_date must be an explicit RFC3339 UTC timestamp")
    datetime.fromisoformat(release_date.replace("Z", "+00:00"))
    if not isinstance(staging_percentage, int) or not -1 <= staging_percentage <= 100:
        raise ValueError("staging_percentage must be -1 or 0..100")
    if not artifacts:
        raise ValueError("Update feed needs at least one artifact")
    names = [_filename(entry["name"]) for entry in artifacts]
    if len(set(blockmaps)) != len(blockmaps) or not set(blockmaps).issubset(names):
        raise ValueError("Blockmaps must name distinct declared artifacts")
    if (len(set(embedded_blockmaps)) != len(embedded_blockmaps)
            or not set(embedded_blockmaps).issubset(names) or set(embedded_blockmaps) & set(blockmaps)
            or embedded_blockmaps and platform != "linux"):
        raise ValueError("Embedded blockmaps must name distinct Linux artifacts")
    destinations = [metadata_name] + names + [name + ".blockmap" for name in blockmaps]
    if len({name.casefold() for name in destinations}) != len(destinations):
        raise ValueError("Duplicate or colliding update output names")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for entry in artifacts:
        name = entry["name"]
        source = Path(entry["source"])
        digest = hashlib.sha512()
        checksums, sizes = [], []
        with source.open("rb") as reader, (output / name).open("wb") as writer:
            chunks = _content_chunks(reader) if name in blockmaps else iter(lambda: reader.read(1024 * 1024), b"")
            for chunk in chunks:
                writer.write(chunk)
                digest.update(chunk)
                if name in blockmaps:
                    checksums.append(base64.b64encode(hashlib.sha256(chunk).digest()).decode("ascii"))
                    sizes.append(len(chunk))
        files.append({"url": quote(name, safe="-._~"), "sha512": base64.b64encode(digest.digest()).decode("ascii"), "size": (output / name).stat().st_size})
        if name in embedded_blockmaps:
            files[-1]["blockMapSize"] = embedded_blockmap_size(source)
        if name in blockmaps:
            data = {"version": "2", "files": [{"name": "file", "offset": 0, "checksums": checksums, "sizes": sizes}]}
            # External updater blockmaps use gzip; embedded AppImage maps use raw deflate.
            with (output / (name + ".blockmap")).open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                    compressed.write(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    result = {"version": version, "files": files, "path": names[0], "sha512": files[0]["sha512"], "releaseDate": release_date}
    if "blockMapSize" in files[0]:
        result["blockMapSize"] = files[0]["blockMapSize"]
    if release_notes:
        result["releaseNotes"] = release_notes
    if staging_percentage != -1:
        result["stagingPercentage"] = staging_percentage
    # JSON is YAML 1.2-compatible and accepted by electron-updater's js-yaml reader.
    (output / metadata_name).write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    for path in output.iterdir():
        path.chmod(0o644)
        os.utime(path, (0, 0))
    return result


if __name__ == "__main__":
    create_feed(output=sys.argv[2], **json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
