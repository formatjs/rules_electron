"""Declared tree views preserve layout and reject selected collisions."""

from pathlib import Path
import tempfile
import unittest

from electron.private.collect_files import collect


class FileCollectionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.tree = self.root / "input"
        self.tree.mkdir()
        (self.tree / ".hidden").write_bytes(b"hidden")
        (self.tree / "helper").write_bytes(b"executable")
        (self.tree / "helper").chmod(0o751)
        self.notice = self.root / "notice"
        self.notice.write_bytes(b"notice")
        self.entries = [{"source": str(self.tree), "path": "", "directory": True},
                        {"source": str(self.notice), "path": "licenses/NOTICE.txt"}]

    def test_root_mount_renaming_modes_and_reproducibility(self):
        output = self.root / "view"
        collect(self.entries, output)
        expected = {".hidden": (b"hidden", 0o644), "helper": (b"executable", 0o755),
                    "licenses/NOTICE.txt": (b"notice", 0o644)}
        self.assertEqual({path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}, set(expected))
        for name, (data, mode) in expected.items():
            path = output / name
            self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777, path.stat().st_mtime), (data, mode, 0))
        self.assertEqual((output / "licenses").stat().st_mtime, 0)
        second = self.root / "again"
        collect(list(reversed(self.entries)), second)
        for name in expected:
            self.assertEqual((second / name).read_bytes(), (output / name).read_bytes())

    def test_rejects_invalid_paths_collisions_and_missing_tools_before_copy(self):
        for paths in [["same", "same"], ["file", "file/child"], ["../escape"], [""]]:
            entries = [{"source": str(self.notice), "path": path} for path in paths]
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                collect(entries, self.root / "bad")
        with self.assertRaisesRegex(ValueError, "require file_matcher"):
            collect(self.entries, self.root / "bad", patterns=["**/*"])
        self.assertFalse((self.root / "bad").exists())

    def test_empty_directories_survive_root_mounts_merges_and_normalization(self):
        (self.tree / "empty/nested").mkdir(parents=True)
        (self.tree / "merged").mkdir(mode=0o700)
        empty = self.root / "empty-tree"
        empty.mkdir()
        entries = self.entries + [{"source": str(empty), "path": "mounted", "directory": True},
                                  {"source": str(self.notice), "path": "merged/notice"}]
        for index, mappings in enumerate((entries, list(reversed(entries)))):
            output = self.root / str(index)
            collect(mappings, output)
            for name in ("empty/nested", "mounted", "merged"):
                path = output / name
                self.assertTrue(path.is_dir())
                self.assertEqual((path.stat().st_mode & 0o777, path.stat().st_mtime), (0o755, 0))
            self.assertEqual(list((output / "empty/nested").iterdir()), [])
            self.assertEqual((output / "merged/notice").read_bytes(), b"notice")
        with self.assertRaisesRegex(ValueError, "collision"):
            collect(entries + [{"source": str(self.notice), "path": "empty"}], self.root / "bad-empty")
        self.assertFalse((self.root / "bad-empty").exists())

    def test_tracked_directory_manifest_rejects_invalid_paths_and_file_collisions(self):
        import json
        manifest = self.root / "directories.json"
        entries = [dict(self.entries[0], directory_manifest=str(manifest))]
        for value in [["../escape"], ["a/./b"], ["/absolute"], [1], {}, ["helper/child"], ["helper"]]:
            manifest.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                collect(entries, self.root / "bad-manifest")
        self.assertFalse((self.root / "bad-manifest").exists())


if __name__ == "__main__":
    unittest.main()
