from pathlib import Path
import tempfile
import unittest

from electron.private.nsis import installer_script, literal


class NsisTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "sample.exe").write_bytes(b"payload")
        self.package = self.root / "package.json"
        self.package.write_text('{"version":"1.2.3"}')

    def render(self, **kwargs):
        return installer_script(self.app, self.package, "org.example.sample", "Sample", "sample", self.root / "setup.exe", **kwargs)

    def test_rejects_unsafe_payloads_before_compilation(self):
        for name in ["Uninstall.exe", ".rules-electron.ini", "bad${__FILE__}", "SAMPLE.exe", "CON"]:
            file = self.app / name
            file.write_bytes(b"bad")
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.render()
            file.unlink()
        (self.app / "link").symlink_to(self.package)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.render()

    def test_literal_dollars_cannot_expand_runtime_variables(self):
        self.assertEqual(literal('Price $5 "quoted"'), '"Price $$5 $\\"quoted$\\""')
        for value in ["${NSISDIR}", "$%HOME%", "line\n!system command", "nul\0"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                literal(value)

    def test_updater_cache_and_version_constraints(self):
        (self.app / "resources").mkdir()
        (self.app / "resources/app-update.yml").write_text('{"updaterCacheDirName":"other"}')
        with self.assertRaisesRegex(ValueError, "cache must match"):
            self.render(updater_cache_name="expected")
        self.package.write_text('{"version":"65536.0.0"}')
        with self.assertRaisesRegex(ValueError, "0..65535"):
            self.render()


if __name__ == "__main__":
    unittest.main()
