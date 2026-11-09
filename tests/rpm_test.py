"""RPM wire integrity, CPIO content and immutable-input regression checks."""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

from electron.private.rpm import build_rpm


def read_header(data, offset):
    assert data[offset:offset + 8] == b"\x8e\xad\xe8\x01\0\0\0\0"
    count, length = struct.unpack_from(">II", data, offset + 8)
    start = offset + 16 + 16 * count
    values = {}
    for index in range(count):
        tag, kind, position, size = struct.unpack_from(">IIII", data, offset + 16 + index * 16)
        value = data[start + position:start + length]
        if kind in (6, 8, 9):
            strings = value.split(b"\0")[:size]
            values[tag] = [item.decode() for item in strings]
        elif kind == 7:
            values[tag] = value[:size]
        elif kind in (3, 4):
            values[tag] = struct.unpack_from(">" + ("H" if kind == 3 else "I") * size, value)
    return values, start + length


def read_cpio(data):
    offset, files = 0, {}
    while True:
        assert data[offset:offset + 6] == b"070701"
        fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        name = data[offset + 110:offset + 110 + fields[11] - 1].decode()
        offset = (offset + 110 + fields[11] + 3) & ~3
        if name == "TRAILER!!!":
            return files
        files[name] = (fields[1], data[offset:offset + fields[6]])
        offset = (offset + fields[6] + 3) & ~3


class RpmTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package.json"
        self.package.write_text(json.dumps({"version": "1.2.3-rc.1+build.8"}))
        self.payload = self.root / "input.tar.gz"
        with tarfile.open(self.payload, "w:gz") as archive:
            info = tarfile.TarInfo("opt/sample/empty")
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(info)
            info = tarfile.TarInfo("opt/sample/世界")
            info.mode, info.size = 0o755, 7
            archive.addfile(info, io.BytesIO(b"payload"))
            info = tarfile.TarInfo("opt/sample/alias")
            info.type, info.linkname = tarfile.SYMTYPE, "世界"
            archive.addfile(info)
        self.options = dict(payload=self.payload, package_json=self.package, package_name="sample", architecture="aarch64",
                            release="8", summary="Sample", description="Sample document app", license="MIT",
                            requires=["glibc >= 2.31", "libc.so.6()(64bit)"], maintainer="Example")

    def test_container_digests_cpio_modes_links_and_reproducibility(self):
        output = self.root / "first.rpm"
        build_rpm(output=output, **self.options)
        data = output.read_bytes()
        self.assertEqual(data[:6], b"\xed\xab\xee\xdb\x03\0")
        signature, end = read_header(data, 96)
        start = (end + 7) & ~7
        tags, payload_start = read_header(data, start)
        metadata, payload = data[start:payload_start], data[payload_start:]
        self.assertEqual(signature[272], [hashlib.sha256(metadata).hexdigest()])
        self.assertEqual(signature[1004], hashlib.md5(data[start:], usedforsecurity=False).digest())
        self.assertEqual(tags[5092], [hashlib.sha256(payload).hexdigest()])
        plain = gzip.decompress(payload)
        self.assertEqual(tags[5097], [hashlib.sha256(plain).hexdigest()])
        files = read_cpio(plain)
        self.assertEqual(files["./opt/sample/世界"], (0o100755, b"payload"))
        self.assertEqual(files["./opt/sample/alias"], (0o120777, "世界".encode()))
        self.assertEqual(files["./opt/sample/empty"], (0o40755, b""))
        self.assertEqual(tags[1001], ["1.2.3~rc.1"])
        self.assertEqual(tags[1022], ["aarch64"])
        self.assertIn("libc.so.6()(64bit)", tags[1049])
        self.assertEqual(tags[1035][1], hashlib.sha256(b"payload").hexdigest())
        before = self.payload.read_bytes()
        os.utime(self.payload, (123456789, 123456789))
        mirror = self.root / "relocated 世界"
        mirror.mkdir()
        copied_payload, copied_package = mirror / "payload.tar.gz", mirror / "manifest.json"
        copied_payload.write_bytes(before)
        copied_package.write_bytes(self.package.read_bytes())
        os.utime(copied_payload, (918273645, 918273645))
        build_rpm(output=mirror / "second.rpm", **dict(self.options, payload=copied_payload, package_json=copied_package))
        self.assertEqual(data, (mirror / "second.rpm").read_bytes())
        self.assertEqual(before, self.payload.read_bytes())

    def test_invalid_metadata_and_unsafe_payloads_fail(self):
        output = self.root / "bad.rpm"
        for change in [{"release": "1-bad"}, {"requires": ["glibc; rm"]}, {"requires": ["rpmlib(Fake)"]},
                       {"license": ""}, {"summary": "NUL\0"}, {"architecture": "arm64"}, {"package_name": "../sample"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_rpm(output=output, **dict(self.options, **change))
        for name in ["../escape", "/absolute", "opt/../escape"]:
            with tarfile.open(self.payload, "w:gz") as archive:
                archive.addfile(tarfile.TarInfo(name))
            with self.subTest(path=name), self.assertRaises(ValueError):
                build_rpm(output=output, **self.options)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
