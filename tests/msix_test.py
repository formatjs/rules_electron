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

from electron.private.msix import BLOCK, FOUNDATION, UAP, UAP3, PackageZip, create_msix, manifest, payload_name


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
                             executable_name="sample", architecture="arm64", build_version="2.3.4.7",
                             protocols=["sample-z", "sample-a"], file_associations={".sample": 'Document <Text> & "Notes"', ".other": "Other document"}, **logos)
            output = root / "first.msix"
            arguments["file_association_icons"] = [
                {"extension": ".sample", "source": logos["logo_44"]},
                {"extension": ".other", "source": logos["logo_150"]},
            ]
            create_msix(output=output, **arguments)
            first = output.read_bytes()
            with ZipFile(output) as archive:
                manifest = ET.fromstring(archive.read("AppxManifest.xml"))
                identity = manifest.find("{" + FOUNDATION + "}Identity")
                self.assertEqual(identity.attrib, dict(Name="org.example.Sample", Publisher="CN=Example", Version="2.3.4.7", ProcessorArchitecture="arm64"))
                self.assertEqual(manifest.find("{" + FOUNDATION + "}Properties/{" + FOUNDATION + "}DisplayName").text, "Sample <Desktop>")
                protocols = manifest.findall(".//{" + UAP3 + "}Protocol")
                self.assertEqual([node.attrib for node in protocols], [
                    {"Name": "sample-a", "Parameters": '"%1"'}, {"Name": "sample-z", "Parameters": '"%1"'},
                ])
                handlers = manifest.findall(".//{" + UAP3 + "}FileTypeAssociation")
                self.assertEqual({node.find("{" + UAP + "}SupportedFileTypes/{" + UAP + "}FileType").text:
                                  node.find("{" + UAP + "}DisplayName").text for node in handlers}, arguments["file_associations"])
                self.assertEqual(len({node.attrib["Name"] for node in handlers}), 2)
                self.assertTrue(all(node.attrib["Parameters"] == '"%1"' and node.attrib["MultiSelectModel"] == "Single" for node in handlers))
                for node in handlers:
                    extension = node.find("{" + UAP + "}SupportedFileTypes/{" + UAP + "}FileType").text
                    icon = node.find("{" + UAP + "}Logo").text
                    source = next(item["source"] for item in arguments["file_association_icons"] if item["extension"] == extension)
                    self.assertEqual(archive.read(icon), Path(source).read_bytes())
                expected = {info.filename: archive.read(info) for info in archive.infolist() if info.filename not in ("AppxBlockMap.xml", "[Content_Types].xml")}
            self.assert_blockmap(first, expected)
            os.utime(app / "sample.exe", (12345, 12345))
            create_msix(output=root / "second.msix", **dict(arguments, protocols=list(reversed(arguments["protocols"])),
                                                          file_association_icons=list(reversed(arguments["file_association_icons"])),
                                                          file_associations=dict(reversed(list(arguments["file_associations"].items())))))
            self.assertEqual(first, (root / "second.msix").read_bytes())
            invalid_png = root / "invalid.png"
            invalid_png.write_bytes(b"not a PNG")
            for icons in [
                [{"extension": ".unregistered", "source": logos["logo_44"]}],
                [arguments["file_association_icons"][0]] * 2,
                [{"extension": ".sample", "source": str(invalid_png)}],
            ]:
                with self.subTest(icons=icons), self.assertRaises(ValueError):
                    create_msix(output=output, **dict(arguments, file_association_icons=icons))
                self.assertEqual(output.read_bytes(), first)
            with self.assertRaisesRegex(ValueError, "CPU"):
                create_msix(output=output, **dict(arguments, architecture="x64"))
            with self.assertRaisesRegex(ValueError, "prerelease"):
                create_msix(output=output, **dict(arguments, build_version=""))
            (app / "empty").mkdir()
            with self.assertRaisesRegex(ValueError, "empty directory"):
                create_msix(output=output, **arguments)

    def test_custom_manifest_preserves_extensions_and_rejects_identity_or_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "app"
            app.mkdir()
            binary = bytearray(256)
            binary[:2] = b"MZ"
            struct.pack_into("<I", binary, 60, 128)
            binary[128:134] = b"PE\0\0" + struct.pack("<H", 0x8664)
            (root / "binary").write_bytes(binary)
            (app / "sample.exe").symlink_to(root / "binary")
            (app / "icon.png").write_bytes(png(44))
            package = root / "package.json"
            package.write_text('{"version":"1.2.3"}')
            supplied = root / "manifest.xml"
            supplied.write_text('''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10" xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10" xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"><Identity Name="org.example.Custom" Publisher="CN=Example" Version="1.2.3.0" ProcessorArchitecture="x64"/><Properties><PublisherDisplayName>Example</PublisherDisplayName><Logo>app\\icon.png</Logo></Properties><Applications><Application Id="Custom" Executable="app\\sample.exe" EntryPoint="Windows.FullTrustApplication"><Extensions><uap:Extension Category="windows.protocol"><uap:Protocol Name="sample-custom"/></uap:Extension></Extensions></Application></Applications><Capabilities><rescap:Capability Name="runFullTrust"/><DeviceCapability Name="microphone"/></Capabilities></Package>''')
            pri = root / "resources.pri"
            pri.write_bytes(b"declared resource index")
            arguments = dict(app=app, package_json=package, identity_name="org.example.Custom", publisher="CN=Example",
                             publisher_display_name="Example", product_name="Custom", executable_name="sample", architecture="x64",
                             manifest_file=supplied, payload_prefix="app", app_is_tree=True, resources_pri=pri)
            output = root / "custom.msix"
            create_msix(output=output, **arguments)
            with ZipFile(output) as archive:
                self.assertEqual(archive.read("AppxManifest.xml"), supplied.read_bytes())
                self.assertEqual(archive.read("app/sample.exe"), binary)
                self.assertEqual(archive.read("resources.pri"), pri.read_bytes())
            for overrides, message in [({"publisher": "CN=Other"}, "identity"), ({"payload_prefix": "other"}, "executable")]:
                rejected = root / "rejected.msix"
                with self.assertRaisesRegex(ValueError, message):
                    create_msix(output=rejected, **dict(arguments, **overrides))
                self.assertFalse(rejected.exists())
            (app / "icon.png").unlink()
            with self.assertRaisesRegex(ValueError, "asset missing"):
                create_msix(output=root / "missing.msix", **arguments)

    def test_rejects_windows_reserved_paths_and_footprints(self):
        for name in ["AppxManifest.xml", "APPXMETADATA/file", "AppxSignature.p7x", "NUL.txt", "dir/COM1", "a./file", "a /file", "a\\b", "a:b", "../file", "/file", "a/", "x" * 261]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                payload_name(name)

    def test_handler_identity_survives_package_version_changes(self):
        names = []
        for version in ("1.0.0.7", "2.0.0.7"):
            data = manifest("org.example.Sample", "CN=Example", "Example", "Sample", "sample.exe", "x64", version, "Sample",
                            file_associations={".sample": "Sample document", ".other": "Other document"})
            root = ET.fromstring(data)
            names.append({node.find("{" + UAP + "}SupportedFileTypes/{" + UAP + "}FileType").text: node.attrib["Name"]
                          for node in root.findall(".//{" + UAP3 + "}FileTypeAssociation")})
        self.assertEqual(names[0], names[1])
        self.assertEqual(len(set(names[0].values())), 2)

    def test_rejects_invalid_handler_declarations(self):
        arguments = dict(identity_name="org.example.Sample", publisher="CN=Example", publisher_display_name="Example",
                         product_name="Sample", executable="sample.exe", architecture="x64", version="1.0.0.7", description="Sample")
        for protocols in [["sample", "sample"], ["SAMPLE"], ["x"], ["scheme/path"], ['sample" injected="true']]:
            with self.subTest(protocols=protocols), self.assertRaisesRegex(ValueError, "protocols"):
                manifest(**arguments, protocols=protocols)
        for associations in [{"sample": "Missing dot"}, {".UPPER": "Uppercase"}, {".a/b": "Path"}, {".sample": ""}, {".sample": "Bad\x00text"}]:
            with self.subTest(associations=associations), self.assertRaises(ValueError):
                manifest(**arguments, file_associations=associations)


if __name__ == "__main__":
    unittest.main()
