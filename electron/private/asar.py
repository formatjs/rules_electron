"""Deterministic regular-file ASAR writer; format defined by electron/asar."""

import hashlib
import json
from pathlib import Path
import shutil
import struct

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


def create_archive(files, destination, unpacked=()):
    """files maps validated relative POSIX paths to regular source files."""
    unpacked = set(unpacked)
    missing = unpacked - files.keys()
    if missing:
        raise ValueError(f"ASAR unpacked paths not declared: {sorted(missing)}")
    header = {"files": {}}
    offset = 0
    packed_sources = []
    for name, source in sorted(files.items()):
        size = source.stat().st_size
        if size > 0xFFFFFFFF:
            raise ValueError(f"ASAR file exceeds 4 GiB limit: {name}")
        node = header
        parts = name.split("/")
        for part in parts[:-1]:
            node = node["files"].setdefault(part, {"files": {}})
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
        output.chmod(files[name].stat().st_mode & 0o777)
