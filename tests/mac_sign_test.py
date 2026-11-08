"""Signing scopes follow declared entitlement policy and real bundle paths."""

from pathlib import Path
import plistlib
import struct
import tempfile
import unittest

from electron.private.mac_sign import signing_arguments, sign_bundle


class MacSignTest(unittest.TestCase):
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
