"""Real rcodesign DMGs preserve payloads; malformed signature layouts fail."""

from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest

from electron.private.dmg import create_dmg
from electron.private.udif import CODE_DIRECTORY, snapshot

XORRISO, CONVERTER, SIGNER = [str(Path(value).resolve()) for value in sys.argv[1:4]]
del sys.argv[1:4]


class UdifTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        bundle = self.root / "Sample.app"
        (bundle / "Contents/MacOS").mkdir(parents=True)
        main = bundle / "Contents/MacOS/sample"
        main.write_bytes(b"immutable executable fixture")
        main.chmod(0o755)
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundlePackageType": "APPL", "CFBundleExecutable": "sample",
        }))
        self.image = self.root / "input.dmg"
        create_dmg(bundle, "Sample.app", "Sample", 0, True, XORRISO, CONVERTER, self.image)
        self.configuration = self.root / "empty.toml"
        self.configuration.write_text("")

    def sign(self, source, output, identifier="org.example.image"):
        subprocess.run([SIGNER, "sign", "--config-file", str(self.configuration), "--timestamp-url", "none",
                        "--signing-time", "2020-01-01T00:00:00Z", "--binary-identifier", "@main:" + identifier,
                        str(source), str(output)], env={"PATH": "", "HOME": str(self.root), "LC_ALL": "C.UTF-8", "TZ": "UTC"},
                       check=True, capture_output=True, timeout=60)

    def test_real_ad_hoc_signing_and_resigning_preserve_payload(self):
        original = self.image.read_bytes()
        unsigned = snapshot(self.image)
        self.assertEqual(unsigned.blobs, {})
        signed_path = self.root / "signed.dmg"
        self.sign(self.image, signed_path)
        signed = snapshot(signed_path)
        self.assertEqual(signed.payload, unsigned.payload)
        self.assertIn(CODE_DIRECTORY, signed.blobs)
        with self.assertRaisesRegex(ValueError, "certificate signature"):
            snapshot(signed_path, require_signature=True)
        resigned_path = self.root / "resigned.dmg"
        self.sign(signed_path, resigned_path, "org.example.other-image")
        resigned = snapshot(resigned_path)
        self.assertEqual(resigned.payload, unsigned.payload)
        self.assertNotEqual(resigned.signature, signed.signature)
        self.assertEqual(self.image.read_bytes(), original)

    def test_snapshot_detects_changed_payload_and_protected_footer(self):
        original = snapshot(self.image)
        for index, offset in enumerate((0, len(self.image.read_bytes()) - 512 + 12)):
            data = bytearray(self.image.read_bytes())
            data[offset] ^= 1
            modified = self.root / ("modified" + str(index) + ".dmg")
            modified.write_bytes(data)
            self.assertNotEqual(snapshot(modified).payload, original.payload)

    def test_rejects_truncated_bounds_duplicate_slots_and_overlapping_blobs(self):
        signed = self.root / "signed.dmg"
        self.sign(self.image, signed)
        original = signed.read_bytes()
        signature_offset = struct.unpack_from(">Q", original, len(original) - 512 + 296)[0]
        cases = []
        data = bytearray(original)
        struct.pack_into(">Q", data, len(data) - 512 + 296, signature_offset + 1)
        cases.append(data)
        data = bytearray(original)
        count = struct.unpack_from(">I", data, signature_offset + 8)[0]
        self.assertGreaterEqual(count, 2)
        first_slot, first_offset = struct.unpack_from(">II", data, signature_offset + 12)
        struct.pack_into(">I", data, signature_offset + 20, first_slot)
        cases.append(data)
        data = bytearray(original)
        struct.pack_into(">I", data, signature_offset + 24, first_offset)
        cases.append(data)
        cases.append(original[:-1])
        for index, data in enumerate(cases):
            path = self.root / ("malformed" + str(index) + ".dmg")
            path.write_bytes(data)
            with self.subTest(index=index), self.assertRaises(ValueError):
                snapshot(path)


if __name__ == "__main__":
    unittest.main()
