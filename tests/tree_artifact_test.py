"""Check empty leaves across producer, collection and ASAR actions on BB."""

import json
from pathlib import Path
import struct
import sys
import unittest

SOURCE, VIEW, ASAR = map(Path, sys.argv[1:])


class TreeArtifactTest(unittest.TestCase):
    def test_remote_tree_and_file_view_preserve_empty_leaves(self):
        for root in (SOURCE, VIEW):
            with self.subTest(root=root.name):
                for name in ("nested/empty", ".hidden/empty"):
                    leaf = root / name
                    self.assertTrue(leaf.is_dir(), name)
                    self.assertEqual(list(leaf.iterdir()), [])
                self.assertEqual((root / "message.txt").read_bytes(), b"tree payload\n")

    def test_separate_asar_action_preserves_empty_directories_and_payload(self):
        data = ASAR.read_bytes()
        _, header_size, _, length = struct.unpack_from("<IIII", data)
        files = json.loads(data[16:16 + length])["files"]
        for parent in ("nested", ".hidden"):
            self.assertEqual(files[parent]["files"]["empty"], {"files": {}})
        self.assertEqual(data[8 + header_size:], b"tree payload\n")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
