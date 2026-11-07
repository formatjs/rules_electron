"""Behavior checks for distribution layout and rejected manifests."""

import json
from pathlib import Path
import tempfile
import unittest

from electron.private.assemble import assemble


class AssemblyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runtime = self.root / "runtime"
        self.runtime.write_bytes(b"runtime")
        self.package = self.root / "package.json"
        self.package.write_text(json.dumps({"main": "main.js"}))
        self.main = self.root / "main.js"
        self.main.write_bytes(b"app")
        self.entries = [
            {"source": str(self.runtime), "path": "electron", "executable": True},
            {"source": str(self.package), "path": "resources/app/package.json"},
            {"source": str(self.main), "path": "resources/app/main.js"},
        ]

    def test_relocatable_layout_and_normalized_metadata(self):
        output = self.root / "distribution"
        assemble(self.entries, output)
        moved = self.root / "moved"
        output.rename(moved)
        for path, content, mode in [
            ("electron", b"runtime", 0o755),
            ("resources/app/main.js", b"app", 0o644),
        ]:
            file = moved / path
            self.assertEqual(file.read_bytes(), content)
            self.assertEqual(file.stat().st_mode & 0o777, mode)
            self.assertEqual(file.stat().st_mtime, 0)
            self.assertFalse(file.is_symlink())

    def test_rejects_invalid_destinations_before_writing(self):
        for path in ["../escape", "/absolute", "a//b", "a/./b", "a/../b", "a\\b", "C:/file", "", "."]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                assemble(self.entries + [{"source": str(self.main), "path": path}], self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_rejects_duplicate_and_overlapping_destinations(self):
        for path in ["electron", "electron/child", "resources", "resources/app.asar"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                assemble(self.entries + [{"source": str(self.main), "path": path}], self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_missing_or_escaping_entry_point(self):
        for main in ["missing.js", "../main.js"]:
            self.package.write_text(json.dumps({"main": main}))
            with self.subTest(main=main), self.assertRaises(ValueError):
                assemble(self.entries, self.root / "out")
        self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
