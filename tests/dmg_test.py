"""Real DMG tools, independent UDIF decoding and immutable bundle checks."""

import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from electron.private.dmg import create_dmg
from electron.private.mac_sign import archive_bundle

XORRISO, CONVERTER = [str(Path(value).resolve()) for value in sys.argv[1:3]]
del sys.argv[1:3]


def decode_dmg(data):
    footer = data[-512:]
    if footer[:4] != b"koly" or struct.unpack_from(">II", footer, 4) != (4, 512):
        raise ValueError("Invalid UDIF footer")
    offset, size = struct.unpack_from(">QQ", footer, 24)
    if zlib.crc32(data[offset:offset + size]) != struct.unpack_from(">I", footer, 88)[0]:
        raise ValueError("Invalid UDIF data checksum")
    xml_offset, xml_size = struct.unpack_from(">QQ", footer, 216)
    resources = plistlib.loads(data[xml_offset:xml_offset + xml_size])
    tables = resources["resource-fork"]["blkx"]
    if len(tables) != 1:
        raise ValueError("Expected whole-disk block map")
    table = tables[0]["Data"]
    if table[:4] != b"mish":
        raise ValueError("Invalid UDIF block map")
    sectors, data_start = struct.unpack_from(">QQ", table, 16)
    result = bytearray(sectors * 512)
    count = struct.unpack_from(">I", table, 200)[0]
    covered = 0
    for index in range(count):
        kind, _, sector, length, compressed, compressed_size = struct.unpack_from(">IIQQQQ", table, 204 + index * 40)
        if kind == 0xffffffff:
            break
        raw = data[offset + data_start + compressed:offset + data_start + compressed + compressed_size]
        if kind == 0x80000005:
            raw = zlib.decompress(raw)
        elif kind != 1:
            raise ValueError("Unsupported UDIF block type")
        if sector != covered or len(raw) != length * 512:
            raise ValueError("Invalid UDIF block length")
        result[sector * 512:(sector + length) * 512] = raw
        covered += length
    if covered != sectors or zlib.crc32(result) != struct.unpack_from(">I", table, 72)[0]:
        raise ValueError("Invalid UDIF uncompressed checksum")
    return bytes(result)


class DmgTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "Original.app"
        (self.bundle / "Contents/MacOS").mkdir(parents=True)
        (self.bundle / "Contents/Resources/empty").mkdir(parents=True)
        (self.bundle / "Contents/_CodeSignature").mkdir()
        self.seal = b"preserve existing signature seal bytes"
        (self.bundle / "Contents/_CodeSignature/CodeResources").write_bytes(self.seal)
        main = self.bundle / "Contents/MacOS/sample"
        main.write_bytes(b"Mach-O fixture bytes")
        main.chmod(0o755)
        (self.bundle / "Contents/Resources/Hello 世界.txt").write_bytes(b"resource bytes")
        (self.bundle / "Contents/Resources/current").symlink_to(".")
        (self.bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "sample", "CFBundlePackageType": "APPL", "CFBundleIdentifier": "org.example.sample",
        }))
        self.source = self.root / "app.zip"
        archive_bundle(self.bundle, self.source, "Original.app")
        self.original = self.source.read_bytes()

    def build(self, source, output, **overrides):
        create_dmg(**dict({"source": source, "app_name": "Sample.app", "volume_name": "Sample", "source_date_epoch": 1577836800,
                           "applications_link": True, "xorriso": XORRISO, "converter": CONVERTER, "output": output}, **overrides))

    def test_dmg_roundtrip_modes_links_unicode_empty_directories_and_existing_seal(self):
        output = self.root / "release.dmg"
        self.build(self.source, output)
        image = decode_dmg(output.read_bytes())
        self.assertEqual(image[512:514], b"PM")
        iso = self.root / "decoded.iso"
        iso.write_bytes(image)
        extracted = self.root / "extracted"
        subprocess.run([XORRISO, "-no_rc", "-local_charset", "UTF-8", "-osirrox", "on", "-indev", str(iso), "-extract", "/", str(extracted)],
                       env={"PATH": "", "HOME": str(self.root), "LC_ALL": "C", "TZ": "UTC"}, check=True, capture_output=True, timeout=60)
        self.assertEqual((extracted / "Applications").readlink().as_posix(), "/Applications")
        app = extracted / "Sample.app/Contents"
        self.assertEqual((app / "_CodeSignature/CodeResources").read_bytes(), self.seal)
        self.assertEqual((app / "MacOS/sample").read_bytes(), b"Mach-O fixture bytes")
        self.assertEqual((app / "MacOS/sample").stat().st_mode & 0o777, 0o755)
        self.assertEqual((app / "Resources/current/Hello 世界.txt").read_bytes(), b"resource bytes")
        self.assertEqual(list((app / "Resources/empty").iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual((output.stat().st_mode & 0o777, output.stat().st_mtime), (0o644, 0))
        damaged = bytearray(output.read_bytes())
        damaged[0] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            decode_dmg(damaged)

    def test_dmg_is_identical_for_zip_and_relocated_tree_with_different_times(self):
        first, second = self.root / "one.dmg", self.root / "two.dmg"
        self.build(self.source, first)
        moved = self.root / "relocated payload.app"
        shutil.copytree(self.bundle, moved, symlinks=True)
        for path in [moved, *moved.rglob("*")]:
            os.utime(path, (1234567890, 1234567890), follow_symlinks=False)
        self.build(moved, second)
        self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())

    def test_invalid_labels_dates_or_bundle_fail_without_output(self):
        for index, options in enumerate([{"volume_name": "a" * 33}, {"app_name": "../Sample.app"},
                                         {"source_date_epoch": -1}, {"source_date_epoch": 2082758400}]):
            output = self.root / (str(index) + ".dmg")
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.build(self.source, output, **options)
            self.assertFalse(output.exists())
        (self.bundle / "Contents/Info.plist").write_bytes(b"not a plist")
        with self.assertRaises(plistlib.InvalidFileException):
            self.build(self.bundle, self.root / "invalid.dmg")
        self.assertFalse((self.root / "invalid.dmg").exists())

    def test_output_cannot_replace_input_or_stage_inside_input_tree(self):
        for source, output in [(self.source, self.source), (self.bundle, self.bundle / "image.dmg")]:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "outside its input"):
                self.build(source, output)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.bundle / "image.dmg").exists())


if __name__ == "__main__":
    unittest.main()
