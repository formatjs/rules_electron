import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from zipfile import ZipFile

from electron.private.zip_parts import assemble, compress

FIXTURE = Path(sys.argv.pop(1))


class ZipPartsTest(unittest.TestCase):
    def test_bazel_actions_produce_standard_zip(self):
        with ZipFile(FIXTURE) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ["package.json"])
            self.assertIn("name", json.loads(archive.read("package.json")))

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
