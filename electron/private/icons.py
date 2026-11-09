"""Validate declared ICNS/ICO containers without host image tools."""

from pathlib import Path
import struct
import zlib


def png_dimensions(path):
    """Read dimensions after validating headers, palette presence and chunk CRCs."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature")
    offset, dimensions, image_data, palette = 8, None, False, False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG payload")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:end - 4]
        if zlib.crc32(kind + payload) != struct.unpack_from(">I", data, end - 4)[0]:
            raise ValueError("PNG checksum mismatch")
        if dimensions is None:
            if kind != b"IHDR" or length != 13:
                raise ValueError("PNG must start with IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if not width or not height or width > 0x7fffffff or height > 0x7fffffff or depth not in depths.get(color, ()) or compression or filtering or interlace not in (0, 1):
                raise ValueError("Invalid PNG image header")
            dimensions = (width, height)
        elif kind == b"IHDR":
            raise ValueError("Duplicate PNG image header")
        if kind == b"PLTE":
            if not length or length % 3 or length > 768 or image_data:
                raise ValueError("Invalid PNG palette")
            palette = True
        if kind == b"IDAT" and color == 3 and not palette:
            raise ValueError("Indexed PNG requires a palette")
        image_data |= kind == b"IDAT" and bool(payload)
        if kind == b"IEND":
            if length or end != len(data) or not image_data:
                raise ValueError("Invalid PNG end chunk")
            return dimensions
        offset = end
    raise ValueError("PNG end chunk missing")


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
