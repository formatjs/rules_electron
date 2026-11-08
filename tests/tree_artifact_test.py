"""Check empty leaves across producer, collection and ASAR actions on BB."""

import json
import io
from pathlib import Path
import struct
import sys
import tarfile
import unittest
from zipfile import ZipFile

SOURCE, VIEW, ASAR, ZIP, TAR, DEB = map(Path, sys.argv[1:])


class TreeArtifactTest(unittest.TestCase):
    def test_remote_tree_and_file_view_preserve_payload(self):
        for root in (SOURCE, VIEW):
            self.assertEqual((root / "message.txt").read_bytes(), b"tree payload\n")

    def test_separate_asar_action_preserves_empty_directories_and_payload(self):
        data = ASAR.read_bytes()
        _, header_size, _, length = struct.unpack_from("<IIII", data)
        files = json.loads(data[16:16 + length])["files"]
        for parent in ("nested", ".hidden"):
            self.assertEqual(files[parent]["files"]["empty"], {"files": {}})
        self.assertEqual(data[8 + header_size:], b"tree payload\n")

    def test_app_and_release_archives_preserve_tracked_directory_paths(self):
        directories = [prefix + suffix for prefix in ("sample/resources/app/assets/", "sample/extra/")
                       for suffix in ("nested/empty", ".hidden/empty")]
        with ZipFile(ZIP) as archive:
            for path in directories:
                entry = archive.getinfo(path + "/")
                self.assertTrue(entry.is_dir())
                self.assertEqual(entry.external_attr >> 16 & 0o777, 0o755)
            self.assertEqual(archive.read("sample/resources/app/assets/message.txt"), b"tree payload\n")
        with tarfile.open(TAR) as archive:
            for path in directories:
                entry = archive.getmember(path)
                self.assertTrue(entry.isdir())
                self.assertEqual((entry.mode, entry.mtime), (0o755, 0))

    def test_deb_payload_preserves_directory_manifest_across_actions(self):
        data = DEB.read_bytes()
        self.assertTrue(data.startswith(b"!<arch>\n"))
        members, offset = {}, 8
        while offset < len(data):
            header = data[offset:offset + 60]
            size = int(header[48:58])
            name = header[:16].decode().strip().removesuffix("/")
            members[name] = data[offset + 60:offset + 60 + size]
            offset += 60 + size + size % 2
        with tarfile.open(fileobj=io.BytesIO(members["data.tar.gz"])) as archive:
            directories = {entry.name.removeprefix("./"): entry for entry in archive.getmembers()}
            for name in ("resources/app/assets/nested/empty", "extra/.hidden/empty"):
                entry = directories["opt/org.example.empty/" + name]
                self.assertTrue(entry.isdir())
                self.assertEqual((entry.mode, entry.mtime), (0o755, 0))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
