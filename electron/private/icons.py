"""Validate declared ICNS containers without platform image tools."""

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
