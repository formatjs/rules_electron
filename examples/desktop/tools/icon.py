"""Deterministic gray ICNS fixture for native bundle icon checks."""

from pathlib import Path
import struct
import sys
import zlib


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(size):
    pixels = (b"\0" + bytes([43, 43, 43, 255]) * size) * size
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    payload = bytearray()
    for kind, size in [(b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024),
                       (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512)]:
        image = png(size)
        payload += kind + struct.pack(">I", len(image) + 8) + image
    Path(sys.argv[1]).write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)
