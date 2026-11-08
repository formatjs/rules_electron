"""Signing scopes follow declared entitlement policy and real bundle paths."""

from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
import shutil
from unittest.mock import patch
from zipfile import ZipFile

from electron.private.mac_sign import signing_arguments, sign_bundle, archive_bundle


class MacSignTest(unittest.TestCase):
    def test_signing_preserves_empty_leaves_and_keeps_input_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "input.app", root / "output.app"
            (source / "Contents/Resources/empty/nested").mkdir(parents=True)
            binary = source / "Contents/MacOS/sample"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"unsigned")

            def sign(command, **_kwargs):
                original, signed = map(Path, command[-2:])
                if original != signed:
                    for file in original.rglob("*"):
                        if file.is_file():
                            destination = signed / file.relative_to(original)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(file, destination)
                (signed / "Contents/MacOS/sample").write_bytes(b"signed")

            with patch("electron.private.mac_sign.subprocess.run", side_effect=sign):
                sign_bundle("declared-signer", source, output)
            self.assertTrue((output / "Contents/Resources/empty/nested").is_dir())
            self.assertEqual(binary.read_bytes(), b"unsigned")
            self.assertEqual((output / "Contents/MacOS/sample").read_bytes(), b"signed")

    def test_bundle_zip_preserves_empty_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "Sample.app"
            (bundle / "Contents/Resources/empty/nested").mkdir(parents=True)
            (bundle / "Contents/Resources/message").write_bytes(b"message")
            output = root / "app.zip"
            archive_bundle(bundle, output, "Sample.app")
            with ZipFile(output) as archive:
                self.assertTrue(archive.getinfo("Sample.app/Contents/Resources/empty/nested/").is_dir())
                self.assertEqual(archive.read("Sample.app/Contents/Resources/message"), b"message")

    def test_scopes_cover_main_nested_binaries_and_skip_aliases_and_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "Sample.app"
            files = {"Contents/MacOS/sample": 2, "Contents/Frameworks/library.dylib": 6,
                     "Contents/Resources/addon.node": 8}
            for name, kind in files.items():
                target = app / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(struct.pack("<8I", 0xfeedfacf, 0x100000c, 0, kind, 0, 0, 0, 0))
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "sample"}))
            (app / "Contents/Resources/Alias.node").symlink_to("addon.node")
            (app / "Contents/Resources/not-native.class").write_bytes(bytes.fromhex("cafebabe0000003d") + bytes(24))
            main, inherited = root / "main.plist", root / "inherited.plist"
            main.write_bytes(plistlib.dumps({"main": True}))
            inherited.write_bytes(plistlib.dumps({"nested": True}))
            arguments = signing_arguments(app, str(main), str(inherited), True)
            entries = list(zip(arguments[::2], arguments[1::2]))
            entitlements = dict(value.rsplit(":", 1) for option, value in entries if option == "--entitlements-xml-file")
            self.assertEqual(entitlements, {
                "@main": str(main), "Contents/MacOS/sample": str(main),
                "Contents/Frameworks/library.dylib": str(inherited), "Contents/Resources/addon.node": str(inherited),
            })
            flags = {value for option, value in entries if option == "--code-signature-flags"}
            self.assertEqual(flags, {"@main:runtime", *(name + ":runtime" for name in files)})

    def test_invalid_entitlements_fail_before_signer_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entitlements = root / "invalid.plist"
            entitlements.write_bytes(plistlib.dumps(["not a dictionary"]))
            output = root / "signed.app"
            with self.assertRaisesRegex(ValueError, "plist dictionary"):
                sign_bundle("/missing-signer", root / "missing.app", output, str(entitlements))
            self.assertFalse(output.exists())
            self.assertFalse((root / "rcodesign.toml").exists())


if __name__ == "__main__":
    unittest.main()
