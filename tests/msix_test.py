"""Decode MSIX records independently; verify ranges, hashes and reproducibility."""

import base64
import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from zipfile import ZipFile
import zlib

from electron.private.msix import BLOCK, FOUNDATION, PackageZip, create_msix, payload_name


def png(size):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff" * size * 4) * size)) + chunk(b"IEND", b""))


class MsixTest(unittest.TestCase):
    def assert_blockmap(self, data, expected):
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            names = {unquote(info.filename): info for info in archive.infolist()}
            blockmap = ET.fromstring(archive.read("AppxBlockMap.xml"))
            self.assertEqual(blockmap.tag, "{" + BLOCK + "}BlockMap")
            self.assertEqual({node.attrib["Name"].replace("\\", "/") for node in blockmap}, set(expected))
            for node in blockmap:
                name = node.attrib["Name"].replace("\\", "/")
                info = names[name]
                header = struct.unpack_from("<IHHHHHIIIHH", data, info.header_offset)
                length = 30 + header[-2] + header[-1]
                self.assertEqual(int(node.attrib["LfhSize"]), length)
                self.assertEqual(int(node.attrib["Size"]), len(expected[name]))
                self.assertEqual(archive.read(info), expected[name])
                cursor = info.header_offset + length
                restored = bytearray()
                for index, block in enumerate(node):
                    size = int(block.attrib.get("Size", min(65536, len(expected[name]) - index * 65536)))
                    compressed = data[cursor:cursor + size]
                    chunk = zlib.decompressobj(-15).decompress(compressed) if info.compress_type == 8 else compressed
                    self.assertEqual(len(chunk), min(65536, len(expected[name]) - index * 65536))
                    self.assertEqual(block.attrib["Hash"], base64.b64encode(hashlib.sha256(chunk).digest()).decode())
                    self.assertEqual("Size" in block.attrib, info.compress_type == 8)
                    restored.extend(chunk)
                    cursor += size
                self.assertEqual(bytes(restored), expected[name])
                if info.compress_type == 8:
                    footer = data[cursor:info.header_offset + length + info.compress_size]
                    decoder = zlib.decompressobj(-15)
                    self.assertEqual(decoder.decompress(footer), b"")
                    self.assertTrue(decoder.eof)
                else:
                    self.assertEqual(cursor, info.header_offset + length + info.compress_size)

    def test_block_ranges_empty_files_unicode_and_stored_payloads(self):
        payloads = {"big data/世界.bin": bytes(range(256)) * 1024 + b"tail", "empty": b"", "exact.bin": b"x" * 65536}
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                output = io.BytesIO()
                writer = PackageZip(output)
                for name, data in payloads.items():
                    writer.add(name, io.BytesIO(data), "application/octet-stream", compressed=compressed)
                writer.close()
                self.assert_blockmap(output.getvalue(), payloads)

    def test_app_identity_cpu_assets_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "app"
            app.mkdir()
            binary = bytearray(512)
            binary[:2] = b"MZ"
            struct.pack_into("<I", binary, 60, 128)
            binary[128:134] = b"PE\0\0" + struct.pack("<H", 0xaa64)
            (app / "sample.exe").write_bytes(binary)
            package = root / "package.json"
            package.write_text('{"version":"2.3.4-beta.1"}')
            logos = {}
            for name, size in [("logo_44", 44), ("logo_150", 150), ("store_logo", 50)]:
                path = root / (name + ".png")
                path.write_bytes(png(size))
                logos[name] = str(path)
            arguments = dict(app=str(app), package_json=str(package), identity_name="org.example.Sample",
                             publisher="CN=Example", publisher_display_name="Example & Co", product_name="Sample <Desktop>",
                             executable_name="sample", architecture="arm64", build_version="2.3.4.7", **logos)
            output = root / "first.msix"
            create_msix(output=output, **arguments)
            first = output.read_bytes()
            with ZipFile(output) as archive:
                manifest = ET.fromstring(archive.read("AppxManifest.xml"))
                identity = manifest.find("{" + FOUNDATION + "}Identity")
                self.assertEqual(identity.attrib, dict(Name="org.example.Sample", Publisher="CN=Example", Version="2.3.4.7", ProcessorArchitecture="arm64"))
                self.assertEqual(manifest.find("{" + FOUNDATION + "}Properties/{" + FOUNDATION + "}DisplayName").text, "Sample <Desktop>")
                expected = {info.filename: archive.read(info) for info in archive.infolist() if info.filename not in ("AppxBlockMap.xml", "[Content_Types].xml")}
            self.assert_blockmap(first, expected)
            os.utime(app / "sample.exe", (12345, 12345))
            create_msix(output=root / "second.msix", **arguments)
            self.assertEqual(first, (root / "second.msix").read_bytes())
            with self.assertRaisesRegex(ValueError, "CPU"):
                create_msix(output=output, **dict(arguments, architecture="x64"))
            with self.assertRaisesRegex(ValueError, "prerelease"):
                create_msix(output=output, **dict(arguments, build_version=""))
            (app / "empty").mkdir()
            with self.assertRaisesRegex(ValueError, "empty directory"):
                create_msix(output=output, **arguments)

    def test_rejects_windows_reserved_paths_and_footprints(self):
        for name in ["AppxManifest.xml", "APPXMETADATA/file", "AppxSignature.p7x", "NUL.txt", "dir/COM1", "a./file", "a /file", "a\\b", "a:b", "../file", "/file", "a/", "x" * 261]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                payload_name(name)


if __name__ == "__main__":
    unittest.main()
