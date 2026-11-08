"""Deterministic ASAR writer; format defined by electron/asar."""

import hashlib
import json
from pathlib import Path
import shutil
import struct

from electron.private.asar_paths import ArchivePaths

BLOCK_SIZE = 4 * 1024 * 1024


def _integrity(path):
    whole = hashlib.sha256()
    blocks = []
    with path.open("rb") as source:
        while block := source.read(BLOCK_SIZE):
            whole.update(block)
            blocks.append(hashlib.sha256(block).hexdigest())
    return {
        "algorithm": "SHA256",
        "hash": whole.hexdigest(),
        "blockSize": BLOCK_SIZE,
        "blocks": blocks or [hashlib.sha256(b"").hexdigest()],
    }


def create_archive(files, destination, unpacked=(), symlinks=None, directories=()):
    """Write declared files, directories and links; hash the raw JSON header."""
    directories = set(directories)
    index = ArchivePaths(files, symlinks, directories)
    unpacked = set(unpacked)
    missing = unpacked - files.keys()
    if missing:
        raise ValueError(f"ASAR unpacked paths not declared: {sorted(missing)}")
    header = {"files": {}}
    offset = 0
    packed_sources = []
    for name in sorted(files.keys() | index.links.keys() | directories):
        node = header
        parts = name.split("/")
        for part in parts[:-1]:
            node = node["files"].setdefault(part, {"files": {}})
        if name in directories:
            node["files"].setdefault(parts[-1], {"files": {}})
            continue
        if name in index.links:
            node["files"][parts[-1]] = {"link": index.links[name]}
            continue
        source = files[name]
        size = source.stat().st_size
        if size > 0xFFFFFFFF:
            raise ValueError(f"ASAR file exceeds 4 GiB limit: {name}")
        entry = {"size": size, "integrity": _integrity(source)}
        if name in unpacked:
            entry["unpacked"] = True
        else:
            entry["offset"] = str(offset)
            offset += size
            packed_sources.append(source)
        if source.stat().st_mode & 0o111:
            entry["executable"] = True
        node["files"][parts[-1]] = entry

    encoded = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload = struct.pack("<I", len(encoded)) + encoded
    payload += b"\0" * (-len(payload) % 4)
    header_pickle = struct.pack("<I", len(payload)) + payload
    destination = Path(destination)
    with destination.open("wb") as archive:
        archive.write(struct.pack("<II", 4, len(header_pickle)))
        archive.write(header_pickle)
        for source in packed_sources:
            with source.open("rb") as content:
                shutil.copyfileobj(content, archive)
    for name in sorted(unpacked):
        output = Path(str(destination) + ".unpacked") / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[name], output)
        output.chmod(0o755 if files[name].stat().st_mode & 0o111 else 0o644)
    return hashlib.sha256(encoded).hexdigest()


def read_header(archive, size):
    """Read a framed ASAR index; return document, raw JSON and data offset."""
    prefix = archive.read(16)
    if len(prefix) != 16:
        raise ValueError("Truncated ASAR header")
    size_size, header_size, payload_size, json_size = struct.unpack("<IIII", prefix)
    if (size_size != 4 or header_size != payload_size + 4 or payload_size % 4
            or not 0 <= payload_size - 4 - json_size <= 3 or header_size + 8 > size):
        raise ValueError("Invalid ASAR header framing")
    raw = archive.read(json_size)
    document = json.loads(raw)
    if len(raw) != json_size or not isinstance(document, dict) or not isinstance(document.get("files"), dict):
        raise ValueError("Invalid ASAR file index")
    return document, raw, header_size + 8


def header_hash(path):
    """Hash only the framed archive's raw JSON header."""
    path = Path(path)
    with path.open("rb") as archive:
        _, raw, _ = read_header(archive, path.stat().st_size)
    return hashlib.sha256(raw).hexdigest()
