"""Check actual app/import/archive/DEB actions preserve resource directory links."""

import io
import json
from pathlib import Path
import stat
import struct
import sys
import tarfile
import tempfile
import unittest
from zipfile import ZipFile

APP, RELEASE, DEB, NOTICE, ASAR, TREE, PLAIN = map(Path, sys.argv[1:])
del sys.argv[1:]


def debian_data(path):
    data = path.read_bytes()
    if data[:8] != b"!<arch>\n":
        raise ValueError("Expected Debian ar archive")
    offset = 8
    while offset < len(data):
        header = data[offset:offset + 60]
        name = header[:16].decode().strip().rstrip("/")
        size = int(header[48:58])
        if name.startswith("data.tar"):
            return data[offset + 60:offset + 60 + size]
        offset += 60 + size + size % 2
    raise ValueError("Missing Debian payload")


class ResourceLinksTest(unittest.TestCase):
    def test_generated_links_survive_collection_and_both_asar_actions(self):
        self.assertFalse(any(path.is_symlink() for path in TREE.rglob("*")))
        self.assertFalse((TREE / "mounted/current").exists())
        with ZipFile(APP) as archive:
            payload = archive.read("app/resources/app.asar")
        for data in (ASAR.read_bytes(), payload):
            length = struct.unpack_from("<I", data, 12)[0]
            files = json.loads(data[16:16 + length])["files"]["assets"]["files"]["mounted"]["files"]
            self.assertEqual(files["current"], {"link": "assets/mounted"})
            self.assertEqual(files["nested"]["files"]["alias"], {"link": "assets/mounted/message.txt"})

    def test_bazel_app_zip_and_both_release_consumers_preserve_real_links(self):
        expected = NOTICE.read_bytes()
        with ZipFile(APP) as archive:
            self.assertTrue(stat.S_ISLNK(archive.getinfo("app/resources/current").external_attr >> 16))
            self.assertEqual(archive.read("app/resources/current"), b"data/v1")
            self.assertEqual(archive.read("app/resources/nested/alias"), b"../current")
            self.assertEqual(archive.read("app/resources/data/v1/notice.txt"), expected)
            self.assertEqual(archive.read("app/resources/generated/mounted/current"), b".")
            self.assertEqual(archive.read("app/resources/generated/mounted/nested/alias"), b"../message.txt")
            self.assertIn("app/resources/app.asar", archive.namelist())
        for contents, prefix in [(RELEASE.read_bytes(), "sample"), (debian_data(DEB), "opt/org.example.links")]:
            with self.subTest(prefix=prefix), tarfile.open(fileobj=io.BytesIO(contents)) as archive:
                current = archive.getmember(prefix + "/resources/current")
                alias = archive.getmember(prefix + "/resources/nested/alias")
                self.assertTrue(current.issym())
                self.assertTrue(alias.issym())
                self.assertEqual((current.linkname, alias.linkname), ("data/v1", "../current"))
                with tempfile.TemporaryDirectory() as directory:
                    archive.extractall(directory, filter="data")
                    root = Path(directory) / prefix / "resources"
                    self.assertEqual((root / "nested/alias/notice.txt").read_bytes(), expected)
                    (root / "data/v1/notice.txt").write_bytes(b"updated")
                    self.assertEqual((root / "current/notice.txt").read_bytes(), b"updated")
                    self.assertEqual((root / "generated/mounted/current/message.txt").read_bytes(), b"tree payload\n")
                    (root / "generated/mounted/message.txt").write_bytes(b"changed generated payload")
                    self.assertEqual((root / "generated/mounted/nested/alias").read_bytes(), b"changed generated payload")
                    extra = Path(directory) / prefix / "licenses/generated/mounted"
                    self.assertEqual((extra / "current/message.txt").read_bytes(), b"tree payload\n")
                    (extra / "message.txt").write_bytes(b"updated extra file")
                    self.assertEqual((extra / "nested/alias").read_bytes(), b"updated extra file")

    def test_plain_app_links_survive_bazel_zip_import_and_tar_actions(self):
        with tarfile.open(PLAIN) as archive, tempfile.TemporaryDirectory() as directory:
            archive.extractall(directory, filter="data")
            root = Path(directory) / "sample"
            for generated in (root / "resources/app/assets/mounted", root / "licenses/generated/mounted"):
                self.assertTrue((generated / "current").is_symlink())
                self.assertEqual((generated / "current/message.txt").read_bytes(), b"tree payload\n")
                (generated / "message.txt").write_bytes(b"plain app update")
                self.assertEqual((generated / "nested/alias").read_bytes(), b"plain app update")


if __name__ == "__main__":
    unittest.main()
