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

from ds_store import DSStore
from mac_alias import Alias

from electron.private.dmg import create_dmg
from electron.private.dmg_licenses import license_image, license_resources
from electron.private.mac_sign import archive_bundle

XORRISO, CONVERTER = [str(Path(value).resolve()) for value in sys.argv[1:3]]
del sys.argv[1:3]


def png(width, height, gray):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + bytes([gray, gray, gray, 255]) * width) * height))
            + chunk(b"IEND", b""))


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


def hfs_volume(image):
    count = struct.unpack_from(">I", image, 512 + 4)[0]
    offsets = [struct.unpack_from(">I", image, block * 512 + 8)[0] * 512
               for block in range(1, count + 1)
               if image[block * 512 + 48:block * 512 + 80].rstrip(b"\0") == b"Apple_HFS"]
    if len(offsets) != 1 or image[offsets[0] + 1024:offsets[0] + 1026] != b"H+":
        raise ValueError("Expected one HFS+ volume")
    return offsets[0]


def catalog_records(image):
    volume = hfs_volume(image)
    header = volume + 1024
    block_size = struct.unpack_from(">I", image, header + 40)[0]
    catalog = volume + struct.unpack_from(">I", image, header + 288)[0] * block_size
    node_size = struct.unpack_from(">H", image, catalog + 32)[0]
    node = struct.unpack_from(">I", image, catalog + 24)[0]
    visited = set()
    while node:
        if node in visited or len(visited) > 10000:
            raise ValueError("Invalid HFS+ catalog chain")
        visited.add(node)
        start = catalog + node * node_size
        count = struct.unpack_from(">H", image, start + 10)[0]
        for index in range(count):
            record = start + struct.unpack_from(">H", image, start + node_size - 2 * (index + 1))[0]
            data = record + 2 + struct.unpack_from(">H", image, record)[0]
            length = struct.unpack_from(">H", image, record + 6)[0]
            name = image[record + 8:record + 8 + 2 * length].decode("utf-16be")
            parent = struct.unpack_from(">I", image, record + 2)[0]
            yield parent, name, data
        node = struct.unpack_from(">I", image, start)[0]


def folder_finder_flags(image):
    return {struct.unpack_from(">I", image, data + 8)[0]: struct.unpack_from(">H", image, data + 56)[0]
            for _, _, data in catalog_records(image) if struct.unpack_from(">H", image, data)[0] == 1}


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
        self.assertEqual(folder_finder_flags(image)[2] & 0x0400, 0)
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

    def test_finder_layout_survives_image_conversion_and_relocation(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress((b"\0" + bytes([43, 43, 43, 255]) * 128) * 128)) + chunk(b"IEND", b""))
        icon_bytes = b"icns" + struct.pack(">I", 16 + len(png)) + b"ic07" + struct.pack(">I", 8 + len(png)) + png
        icon = self.root / "volume.icns"
        icon.write_bytes(icon_bytes)
        options = dict(finder_window=[120, 140, 600, 360], app_position=[140, 160],
                       applications_position=[460, 160], icon_size=112, text_size=12,
                       background_color="#ddeeff", volume_icon=icon)
        first, second = self.root / "layout.dmg", self.root / "relocated-layout.dmg"
        self.build(self.source, first, **options)
        image = decode_dmg(first.read_bytes())
        flags = folder_finder_flags(image)
        self.assertEqual(flags[2] & 0x0400, 0x0400)
        self.assertTrue(all(not value & 0x0400 for identity, value in flags.items() if identity != 2))
        iso = self.root / "layout.iso"
        iso.write_bytes(image)
        extracted = self.root / "finder-volume"
        subprocess.run([XORRISO, "-no_rc", "-osirrox", "on", "-indev", str(iso), "-extract", "/", str(extracted)],
                       env={"PATH": "", "HOME": str(self.root), "LC_ALL": "C", "TZ": "UTC"},
                       check=True, capture_output=True, timeout=60)
        self.assertEqual((extracted / ".VolumeIcon.icns").read_bytes(), icon_bytes)
        with DSStore.open(str(extracted / ".DS_Store"), "r") as store:
            self.assertEqual(store["Sample.app"]["Iloc"], (140, 160))
            self.assertEqual(store["Applications"]["Iloc"], (460, 160))
            self.assertEqual(store["."]["bwsp"]["WindowBounds"], "{{120, 140}, {600, 360}}")
            self.assertEqual(store["."]["icvl"], (b"type", b"icnv"))
            settings = store["."]["icvp"]
            self.assertEqual((settings["iconSize"], settings["textSize"], settings["arrangeBy"]), (112.0, 12.0, "none"))
            self.assertEqual(settings["backgroundType"], 1)
            self.assertEqual([settings[key] for key in ["backgroundColorRed", "backgroundColorGreen", "backgroundColorBlue"]],
                             [221 / 255, 238 / 255, 1.0])
        volume = hfs_volume(image)
        self.assertEqual(image[volume + 1024:volume + 1026], b"H+")
        self.assertEqual(struct.unpack_from(">I", image, volume + 1024 + 88)[0], 2)
        moved = self.root / "moved.app"
        shutil.copytree(self.bundle, moved, symlinks=True)
        for item in [moved, *moved.rglob("*")]:
            os.utime(item, (1234567890, 1234567890), follow_symlinks=False)
        moved_icon = self.root / "moved.icns"
        moved_icon.write_bytes(icon_bytes)
        os.utime(moved_icon, (1234567890, 1234567890))
        self.build(moved, second, **dict(options, volume_icon=moved_icon))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual((extracted / "Sample.app/Contents/_CodeSignature/CodeResources").read_bytes(), self.seal)
        self.assertEqual(self.source.read_bytes(), self.original)
        with self.assertRaisesRegex(ValueError, "outside its inputs"):
            self.build(self.source, icon, volume_icon=icon)
        self.assertEqual(icon.read_bytes(), icon_bytes)
        invalid_icon = self.root / "invalid.icns"
        invalid_icon.write_bytes(b"not an icon")
        with self.assertRaisesRegex(ValueError, "ICNS"):
            self.build(self.source, self.root / "invalid-icon.dmg", volume_icon=invalid_icon)
        self.assertFalse((self.root / "invalid-icon.dmg").exists())

    def test_invalid_finder_layout_never_creates_an_image(self):
        for index, options in enumerate([
            {"finder_window": [1, 2, 3]}, {"finder_window": [0, 0, 0, 400]},
            {"app_position": [-1, 100]}, {"applications_position": [640, 100]},
            {"icon_size": 15}, {"text_size": 17}, {"background_color": "white"},
        ]):
            output = self.root / ("bad-layout-" + str(index) + ".dmg")
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.build(self.source, output, **dict({"finder_window": [100, 100, 640, 400]}, **options))
            self.assertFalse(output.exists())

    def test_background_image_alias_is_volume_relative_and_reproducible(self):
        background = self.root / "outside build directory.png"
        pixels = png(600, 360, 173)
        background.write_bytes(pixels)
        options = dict(finder_window=[120, 140, 600, 360], app_position=[140, 160],
                       applications_position=[460, 160], background_image=background,
                       volume_name="Sample 世界")
        first, second = self.root / "picture.dmg", self.root / "moved-picture.dmg"
        self.build(self.source, first, **options)
        image = decode_dmg(first.read_bytes())
        iso = self.root / "picture.iso"
        iso.write_bytes(image)
        extracted = self.root / "picture-volume"
        subprocess.run([XORRISO, "-no_rc", "-osirrox", "on", "-indev", str(iso), "-extract", "/", str(extracted)],
                       env={"PATH": "", "HOME": str(self.root), "LC_ALL": "C", "TZ": "UTC"},
                       check=True, capture_output=True, timeout=60)
        self.assertEqual((extracted / ".background.png").read_bytes(), pixels)
        with DSStore.open(str(extracted / ".DS_Store"), "r") as store:
            settings = store["."]["icvp"]
            self.assertEqual(settings["backgroundType"], 2)
            data = settings["backgroundImageAlias"]
        alias = Alias.from_bytes(data)
        self.assertEqual(alias.volume.name, "Sample 世界")
        self.assertIsNone(alias.volume.posix_path)
        self.assertIsNone(alias.target.folder_name)
        self.assertEqual(alias.volume.disk_type, 5)
        self.assertEqual((alias.target.filename, alias.target.posix_path, alias.target.carbon_path),
                         (".background.png", "/.background.png", "Sample 世界:.background.png".encode("utf-8")))
        self.assertEqual(alias.target.folder_cnid, 2)
        self.assertGreaterEqual(alias.target.cnid, 16)
        self.assertNotIn(str(self.root).encode(), data)
        volume_date = struct.unpack_from(">I", image, hfs_volume(image) + 1024 + 16)[0]
        self.assertEqual(struct.unpack_from(">I", data, 38)[0], volume_date)
        background_records = [record for parent, name, record in catalog_records(image)
                              if parent == 2 and name == ".background.png"]
        self.assertEqual(len(background_records), 1)
        background_id = struct.unpack_from(">I", image, background_records[0] + 8)[0]
        self.assertEqual(alias.target.cnid, background_id)
        background_date = struct.unpack_from(">I", image, background_records[0] + 12)[0]
        self.assertEqual(struct.unpack_from(">I", data, 118)[0], background_date)
        moved = self.root / "moved inputs"
        moved.mkdir()
        moved_background = moved / "different name.png"
        moved_background.write_bytes(pixels)
        os.utime(moved_background, (1234567890, 1234567890))
        moved_app = moved / "different.app"
        shutil.copytree(self.bundle, moved_app, symlinks=True)
        self.build(moved_app, second, **dict(options, background_image=moved_background))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        background.write_bytes(png(600, 360, 174))
        self.build(self.source, second, **options)
        self.assertNotEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual((extracted / "Sample.app/Contents/_CodeSignature/CodeResources").read_bytes(), self.seal)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_background_rejects_missing_layout_bad_png_dimensions_and_output_alias(self):
        background = self.root / "background.png"
        valid = png(64, 64, 173)
        background.write_bytes(valid)
        with self.assertRaisesRegex(ValueError, "requires finder_window"):
            self.build(self.source, self.root / "no-window.dmg", background_image=background)
        self.assertFalse((self.root / "no-window.dmg").exists())
        with self.assertRaisesRegex(ValueError, "outside its inputs"):
            self.build(self.source, background, background_image=background, finder_window=[0, 0, 640, 400])
        self.assertEqual(background.read_bytes(), valid)
        damaged = bytearray(valid)
        damaged[29] ^= 1
        for payload in [b"not PNG", valid[:-1], bytes(damaged), png(8193, 1, 173)]:
            background.write_bytes(payload)
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                self.build(self.source, self.root / "invalid-picture.dmg", background_image=background,
                           finder_window=[0, 0, 640, 400])
            self.assertFalse((self.root / "invalid-picture.dmg").exists())
        with background.open('wb') as oversized:
            oversized.write(valid)
            oversized.seek(64 * 1024**2)
            oversized.write(b'\0')
        with self.assertRaisesRegex(ValueError, '64 MiB'):
            self.build(self.source, self.root / 'oversized-picture.dmg', background_image=background,
                       finder_window=[0, 0, 640, 400])
        self.assertFalse((self.root / 'oversized-picture.dmg').exists())
        self.assertEqual(background.stat().st_size, 64 * 1024**2 + 1)

    def test_output_cannot_replace_input_or_stage_inside_input_tree(self):
        for source, output in [(self.source, self.source), (self.bundle, self.bundle / "image.dmg")]:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "outside its input"):
                self.build(source, output)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.bundle / "image.dmg").exists())

    def test_plain_licenses_use_locale_encoding_without_utf8_or_rtf_markup(self):
        text = self.root / 'english.txt'
        text.write_bytes('Café\r\nLicense\n'.encode('utf-8-sig'))
        resources = license_resources([{'source': str(text), 'locale': 'en_US'}])
        self.assertEqual(resources['TEXT'][0]['Data'], b'Caf\x8e\rLicense\r')
        self.assertNotIn('RTF ', resources)
        japanese = self.root / 'japanese.txt'
        japanese.write_text('日本語\n', encoding='utf-8')
        resources = license_resources([{'source': str(japanese), 'locale': 'ja_JP'}], 'ja_JP')
        self.assertEqual(resources['TEXT'][0]['Data'], b'\x93\xfa\x96\x7b\x8c\xea\r')

    def test_license_resources_preserve_disk_payload_and_relocate_identically(self):
        base = self.root / 'base.dmg'
        self.build(self.source, base)
        original = base.read_bytes()
        text = self.root / 'english.txt'
        text.write_text('License {fixture} \\ text\nUnicode: 世界 😀\n', encoding='utf-8')
        rich = self.root / 'japanese.rtf'
        rich_bytes = b'{\\rtf1\\ansi RTF fixture \\u26085?\\u26412?}'
        rich.write_bytes(rich_bytes)
        labels = self.root / 'labels.json'
        labels.write_text('{"en_US":{"languageName":"English","agree":"Accept"},"ja_JP":{"languageName":"日本語"}}', encoding='utf-8')
        entries = [{'source': str(text), 'locale': 'en_US'}, {'source': str(rich), 'locale': 'ja_JP'}]
        first, second = self.root / 'licensed.dmg', self.root / 'relocated-licensed.dmg'
        license_image(base, first, entries, default_language='ja_JP', labels=labels)
        data = first.read_bytes()
        xml_offset, xml_size = struct.unpack_from('>QQ', data, len(data) - 512 + 216)
        metadata = plistlib.loads(data[xml_offset:xml_offset + xml_size])['resource-fork']
        self.assertEqual(data[:xml_offset], original[:xml_offset])
        self.assertEqual(decode_dmg(data), decode_dmg(original))
        self.assertEqual(base.read_bytes(), original)
        self.assertEqual(metadata['LPic'][0]['Data'], struct.pack('>hHhhhhhh', 14, 2, 0, 0, 0, 14, 1, 1))
        bodies = {entry['ID']: entry['Data'] for entry in metadata['RTF ']}
        self.assertEqual(bodies['5001'], rich_bytes)
        self.assertIn(b'License \\{fixture\\} \\\\ text\\par', bodies['5000'])
        self.assertIn(b'\\u19990?\\u30028?', bodies['5000'])
        self.assertIn(b'\\u-10179?\\u-8704?', bodies['5000'])
        strings = {entry['ID']: entry['Data'] for entry in metadata['STR#']}
        self.assertEqual(struct.unpack_from('>H', strings['5000'])[0], 6)
        offset, decoded = 2, []
        while offset < len(strings['5000']):
            length = strings['5000'][offset]
            decoded.append(strings['5000'][offset + 1:offset + 1 + length].decode('mac_roman'))
            offset += 1 + length
        self.assertEqual(decoded[:3], ['English', 'Accept', 'Disagree'])
        moved = self.root / 'different inputs'
        moved.mkdir()
        relocated = []
        for entry in reversed(entries):
            source = Path(entry['source'])
            destination = moved / ('renamed-' + source.name)
            destination.write_bytes(source.read_bytes())
            os.utime(destination, (1234567890, 1234567890))
            relocated.append(dict(entry, source=str(destination)))
        license_image(base, second, relocated, default_language='ja_JP', labels=labels)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertNotEqual(data[-512 + 64:-512 + 80], original[-512 + 64:-512 + 80])
        self.assertEqual(first.stat().st_mtime, 0)

    def test_license_failures_preserve_inputs_and_existing_output(self):
        base = self.root / 'base.dmg'
        self.build(self.source, base)
        original = base.read_bytes()
        text = self.root / 'license.txt'
        text.write_text('Generic license fixture', encoding='utf-8')
        entries = [{'source': str(text), 'locale': 'en_US'}]
        output = self.root / 'existing.dmg'
        output.write_bytes(b'competing output')
        cases = [([], 'en_US'), (entries * 2, 'en_US'), (entries, 'ja_JP'),
                 ([dict(entries[0], locale='invalid')], 'invalid')]
        for licenses, default in cases:
            with self.subTest(default=default, count=len(licenses)), self.assertRaises(ValueError):
                license_image(base, output, licenses, default)
            self.assertEqual(output.read_bytes(), b'competing output')
        for target in [base, text]:
            with self.assertRaisesRegex(ValueError, 'outside its inputs'):
                license_image(base, target, entries)
        signed = bytearray(original)
        struct.pack_into('>QQ', signed, len(signed) - 512 + 296, 1, 12)
        damaged = self.root / 'signed.dmg'
        damaged.write_bytes(signed)
        with self.assertRaisesRegex(ValueError, 'unsigned image'):
            license_image(damaged, output, entries)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            license_image(self._licensed_image(base, entries), output, entries)
        self.assertEqual(base.read_bytes(), original)
        self.assertEqual(text.read_text(), 'Generic license fixture')
        self.assertEqual(output.read_bytes(), b'competing output')
        labels = self.root / 'bad-labels.json'
        labels.write_text('{"en_US":{"agree":"' + 'x' * 256 + '"}}')
        with self.assertRaisesRegex(ValueError, '255 encoded bytes'):
            license_resources(entries, labels=labels)
        text.write_bytes(b'bad\0text')
        with self.assertRaisesRegex(ValueError, 'controls'):
            license_resources(entries)

    def _licensed_image(self, base, entries):
        output = self.root / 'already-licensed.dmg'
        license_image(base, output, entries)
        return output


if __name__ == "__main__":
    unittest.main()
