"""Release identity stays consistent across app and updater artifacts."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from electron.private.identity import build_identity, package_json
from electron.private.update import create_feed


class IdentityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_bazel_manifest_override_reaches_app_and_feed(self):
        package = json.loads(PACKAGE.read_text())
        packaged = json.loads((APP / "resources/app/package.json").read_text())
        self.assertEqual(package["version"], "3.2.1-beta.2+build.7")
        self.assertEqual(packaged, package)
        artifact = self.root / "release.tar.gz"
        artifact.write_bytes(b"final release artifact")
        result = create_feed(
            [{"source": artifact, "name": "release.tar.gz"}], PACKAGE,
            self.root / "feed", "linux", "x64", "2026-01-02T03:04:05Z", channel="beta",
        )
        self.assertEqual(result["version"], packaged["version"])
        self.assertNotIn("build_number", packaged)

    def test_manifest_is_stable_preserves_metadata_and_keeps_source(self):
        source = self.root / "package.json"
        original = {"name": "sample", "version": "1.2.3", "description": "世界", "scripts": {"build": "development"}}
        source.write_text(json.dumps(original))
        first, second = self.root / "first.json", self.root / "second.json"
        package_json(source, first, "2.3.4-rc.1+build.5", remove_scripts=True)
        self.assertEqual(json.loads(source.read_text()), original)
        source.write_text(json.dumps(dict(reversed(list(original.items())))))
        package_json(source, second, "2.3.4-rc.1+build.5", remove_scripts=True)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(json.loads(first.read_text()), {
            "name": "sample", "description": "世界", "version": "2.3.4-rc.1+build.5",
        })

    def test_invalid_versions_fail_before_output(self):
        source, output = self.root / "package.json", self.root / "result.json"
        for version in [None, 7, "", "1.2", "01.2.3", "1.2.3-01", "1.2.3+", "1.2.3\n"]:
            source.write_text(json.dumps({"version": version}))
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "SemVer"):
                package_json(source, output)
            self.assertFalse(output.exists())
        source.write_text("[]")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            package_json(source, output)

    def test_native_build_override_precedence_and_windows_limits(self):
        self.assertEqual(build_identity("1.2.3-beta.2+build.5", build_number="7"), "1.2.3.7")
        self.assertEqual(build_identity("1.2.3", "4.5.6.8", "7", "windows"), "4.5.6.8")
        for options in [
            {"build_number": "-1"}, {"build_number": "01"}, {"build_number": "1.2"},
            {"build_version": "1.2.3.4.5"}, {"build_version": "1.2.3-beta"},
            {"build_number": "65536", "platform": "windows"},
            {"build_version": "65536", "platform": "windows"},
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                build_identity("1.2.3", **options)


if __name__ == "__main__":
    PACKAGE, APP = [Path(sys.argv.pop(1)) for _ in range(2)]
    unittest.main()
