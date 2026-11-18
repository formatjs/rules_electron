import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from electron.private.zip_parts import assemble, compress, layout, member, merge

FIXTURE = Path(sys.argv.pop(1))
MEMBERS_FIXTURE = Path(sys.argv.pop(1))
LARGE_TREE_FIXTURE = Path(sys.argv.pop(1))


class ZipPartsTest(unittest.TestCase):
    def test_bazel_actions_produce_standard_zip(self):
        with ZipFile(FIXTURE) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ["package.json"])
            self.assertIn("name", json.loads(archive.read("package.json")))
        with ZipFile(MEMBERS_FIXTURE) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("app/resources/app/main.js", archive.namelist())

    def test_large_tree_batches_fit_execution_argument_limits(self):
        with ZipFile(LARGE_TREE_FIXTURE) as archive:
            self.assertIsNone(archive.testzip())
            members = [info for info in archive.infolist() if not info.is_dir()]
            self.assertEqual(len(members), 1000)
            self.assertTrue(all(archive.read(info) == b"x" for info in members))

    def test_merge_preserves_cached_members_unicode_empty_directories_and_zip64(self):
        with tempfile.TemporaryDirectory() as work, patch("zipfile.ZIP64_LIMIT", 64):
            root = Path(work)
            app = root / "app"
            (app / "empty").mkdir(parents=True)
            runtime = app / "runtime.exe"
            runtime.write_bytes(bytes(range(256)) * 4)
            runtime.chmod(0o755)
            sidecar = app / "sidecar.exe"
            sidecar.write_bytes(b"first")
            text = app / "文.txt"
            text.write_bytes(b"hello")
            parts = root / "members"
            parts.mkdir()
            for path in [runtime, sidecar, text]:
                member([{"source": str(path), "prefix": "app/" + path.name, "directory": False}], parts / (path.name + ".zip"), 6)
            stable = (parts / "runtime.exe.zip").read_bytes()
            description = root / "layout.json"
            sources = [{"source": str(app), "prefix": "app", "directory": True}]
            layout(sources, "windows", description)
            output = root / "output.zip"
            merge(parts, description, output)
            with ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read("app/runtime.exe"), runtime.read_bytes())
                self.assertEqual(archive.read("app/文.txt"), b"hello")
                self.assertTrue(archive.getinfo("app/empty/").is_dir())
                self.assertEqual(archive.getinfo("app/runtime.exe").external_attr >> 16, stat.S_IFREG | 0o755)
            sidecar.write_bytes(b"second")
            member([{"source": str(sidecar), "prefix": "app/sidecar.exe", "directory": False}], parts / "sidecar.exe.zip", 6)
            merge(parts, description, output)
            self.assertEqual((parts / "runtime.exe.zip").read_bytes(), stable)
            with ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read("app/sidecar.exe"), b"second")
            (parts / "sidecar.exe.zip").unlink()
            with self.assertRaisesRegex(ValueError, "do not match layout"):
                merge(parts, description, output)

    def test_bounded_parts_round_trip_metadata_links_and_deterministic_bytes(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            app = root / "app"
            (app / "empty").mkdir(parents=True)
            binary = app / "binary"
            binary.write_bytes(bytes(range(256)) * 4)
            binary.chmod(0o755)
            (app / "link").symlink_to("binary")
            manifest = root / "manifest.xml"
            manifest.write_text("<app/>")
            sources = [{"source": str(app), "prefix": "Example.app", "directory": True},
                       {"source": str(manifest), "prefix": "manifest.xml", "directory": False}]
            outputs = []
            for name, size in [("small", 64), ("large", 1024)]:
                parts = root / name
                compress(sources, "macos", 0, parts, part_size=size)
                index = json.loads((parts / "index.json").read_text())
                self.assertGreater(index["parts"], 1)
                self.assertTrue(all(path.stat().st_size <= size for path in parts.iterdir() if path.name != "index.json"))
                output = root / (name + ".zip")
                assemble(parts, output)
                outputs.append(output.read_bytes())
            self.assertEqual(*outputs)
            with ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read("Example.app/binary"), binary.read_bytes())
                self.assertEqual(archive.read("manifest.xml"), b"<app/>")
                self.assertEqual(archive.read("Example.app/link"), b"binary")
                self.assertTrue(archive.getinfo("Example.app/empty/").is_dir())
                self.assertEqual(archive.getinfo("Example.app/binary").external_attr >> 16, stat.S_IFREG | 0o755)
                self.assertEqual(archive.getinfo("Example.app/link").external_attr >> 16, stat.S_IFLNK | 0o777)
                self.assertEqual(archive.getinfo("manifest.xml").date_time, (1980, 1, 1, 0, 0, 0))
            (parts / "00000000").unlink()
            with self.assertRaisesRegex(ValueError, "parts missing"):
                assemble(parts, output)

    def test_windows_case_collisions_rejected_before_archive_creation(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            app = root / "app"
            app.mkdir()
            (app / "Case").write_bytes(b"one")
            (app / "case").write_bytes(b"two")
            with self.assertRaisesRegex(ValueError, "Case-insensitive"):
                compress([{"source": str(app), "prefix": "app", "directory": True}], "windows", 6, root / "parts")


if __name__ == "__main__":
    unittest.main()
