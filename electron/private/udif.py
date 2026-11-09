"""Snapshot signed DMG payloads and embedded blobs without trusting signatures."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

CODE_DIRECTORY = 0
CMS = 0x10000
TICKET = 0x10002


@dataclass(frozen=True)
class Image:
    payload: tuple
    blobs: dict

    @property
    def signature(self):
        return {slot: blob for slot, blob in self.blobs.items() if slot != TICKET}


def snapshot(path, require_signature=False, require_ticket=False):
    path = Path(path)
    size = path.stat().st_size
    if not 512 <= size <= 16 * 1024**3:
        raise ValueError("DMG size exceeds limits")
    with path.open("rb") as source:
        source.seek(-512, 2)
        trailer = source.read(512)
        if trailer[:4] != b"koly" or struct.unpack_from(">II", trailer, 4) != (4, 512):
            raise ValueError("Invalid DMG trailer")
        if struct.unpack_from(">II", trailer, 56) != (1, 1):
            raise ValueError("Expected single-segment DMG")
        data_offset, data_size, resource_offset, resource_size = struct.unpack_from(">QQQQ", trailer, 24)
        xml_offset, xml_size = struct.unpack_from(">QQ", trailer, 216)
        content_size = xml_offset + xml_size
        if (not data_size or not xml_size or data_offset + data_size > xml_offset
                or resource_size and resource_offset + resource_size > xml_offset
                or content_size > size - 512):
            raise ValueError("Invalid DMG payload bounds")
        signature_offset, signature_size = struct.unpack_from(">QQ", trailer, 296)
        blobs = {}
        if signature_offset or signature_size:
            if (signature_offset != content_size or not 12 <= signature_size <= 64 * 1024**2
                    or signature_offset + signature_size != size - 512):
                raise ValueError("Invalid DMG signature bounds")
            source.seek(signature_offset)
            signature = source.read(signature_size)
            magic, length, count = struct.unpack_from(">III", signature)
            if magic != 0xfade0cc0 or length != signature_size or not 1 <= count <= 128 or 12 + count * 8 > length:
                raise ValueError("Invalid DMG signature index")
            ranges = []
            for index in range(count):
                slot, offset = struct.unpack_from(">II", signature, 12 + index * 8)
                if slot in blobs or offset < 12 + count * 8 or offset + 8 > length:
                    raise ValueError("Invalid DMG signature slot")
                _, blob_size = struct.unpack_from(">II", signature, offset)
                if blob_size < 8 or offset + blob_size > length:
                    raise ValueError("Invalid DMG signature blob")
                ranges.append((offset, offset + blob_size))
                blobs[slot] = signature[offset:offset + blob_size]
            ordered = sorted(ranges)
            if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
                raise ValueError("Overlapping DMG signature blobs")
            directory = blobs.get(CODE_DIRECTORY, b"")
            if len(directory) < 44 or directory[:4] != b"\xfa\xde\x0c\x02":
                raise ValueError("Missing DMG code directory")
            for slot in (CMS, TICKET):
                if slot in blobs and blobs[slot][:4] != b"\xfa\xde\x0b\x01":
                    raise ValueError("Invalid DMG signature wrapper")
        elif content_size != size - 512:
            raise ValueError("Unexpected unsigned DMG padding")
        if require_signature or require_ticket:
            if len(blobs.get(CMS, b"")) <= 8 or struct.unpack_from(">I", blobs[CODE_DIRECTORY], 12)[0] & 2:
                raise ValueError("DMG requires certificate signature")
        if require_ticket and len(blobs.get(TICKET, b"")) <= 8:
            raise ValueError("Missing DMG notarization ticket")
        digest = hashlib.sha256()
        source.seek(0)
        remaining = content_size
        while remaining:
            block = source.read(min(remaining, 1024**2))
            if not block:
                raise ValueError("Truncated DMG payload")
            digest.update(block)
            remaining -= len(block)
    canonical = trailer[:296] + bytes(16) + trailer[312:]
    return Image((content_size, digest.hexdigest(), canonical), blobs)
