"""Validate declared ICNS/ICO containers without host image tools."""

from pathlib import Path
import struct


def validate_icns(path):
    data = Path(path).read_bytes()
    if len(data) < 16 or data[:4] != b"icns" or struct.unpack_from(">I", data, 4)[0] != len(data):
        raise ValueError("Invalid macOS ICNS header")
    offset, payload = 8, False
    while offset < len(data):
        if len(data) - offset < 8:
            raise ValueError("Truncated ICNS chunk")
        size = struct.unpack_from(">I", data, offset + 4)[0]
        if size < 8 or size > len(data) - offset:
            raise ValueError("Invalid ICNS chunk length")
        payload |= size > 8
        offset += size
    if not payload:
        raise ValueError("ICNS container has no image payload")


def validate_ico(path):
    data = Path(path).read_bytes()
    if len(data) < 6:
        raise ValueError("Truncated ICO header")
    reserved, kind, count = struct.unpack_from("<HHH", data)
    directory_end = 6 + count * 16
    if reserved or kind != 1 or not count or directory_end > len(data):
        raise ValueError("Invalid ICO directory")
    for entry in range(6, directory_end, 16):
        size, offset = struct.unpack_from("<II", data, entry + 8)
        if data[entry + 3] or not size or offset < directory_end or offset + size > len(data):
            raise ValueError("Invalid ICO image range")
