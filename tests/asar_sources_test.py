"""Standalone ASAR layout, deterministic bytes and rejected source mappings."""

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from electron.private.asar import header_hash
from electron.private.asar_sources import write_sources


class AsarSourcesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.module = self.root / "module.cjs"
        self.module.write_bytes(b"module.exports = 7;\n")
        self.tree = self.root / "tree"
        self.tree.mkdir()
        (self.tree / "message.txt").write_text("Hello, 世界", encoding="utf-8")
        self.module.chmod(0o751)
        self.entries = [{"source": str(self.module), "path": "module.cjs"},
                        {"source": str(self.tree), "path": "assets", "directory": True}]

    def test_archive_payload_unpacked_tree_and_reproducibility(self):
        archive = self.root / "one.asar"
        digest = write_sources(self.entries, archive, ["module.cjs"])
        data = archive.read_bytes()
        _, header_size, _, length = struct.unpack_from("<IIII", data)
        raw = data[16:16 + length]
        header = json.loads(raw)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(header_hash(archive), digest)
        module = header["files"]["module.cjs"]
        self.assertTrue(module["unpacked"])
        self.assertTrue(module["executable"])
        self.assertNotIn("offset", module)
        unpacked = Path(str(archive) + ".unpacked/module.cjs")
        self.assertEqual(unpacked.read_bytes(), self.module.read_bytes())
        self.assertEqual(unpacked.stat().st_mode & 0o777, 0o755)
        self.assertEqual(unpacked.stat().st_mtime, 0)
        message = header["files"]["assets"]["files"]["message.txt"]
        offset = 8 + header_size + int(message["offset"])
        self.assertEqual(data[offset:offset + message["size"]], "Hello, 世界".encode())
        second = self.root / "two.asar"
        write_sources(list(reversed(self.entries)), second, ["module.cjs"])
        self.assertEqual(second.read_bytes(), data)

    def test_rejects_invalid_or_colliding_inputs(self):
        for path in ["../escape", "/absolute", "a/../b", "module.cjs", "module.cjs/child"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                write_sources(self.entries + [{"source": str(self.module), "path": path}], self.root / "bad.asar")
        with self.assertRaisesRegex(ValueError, "unpacked paths not declared"):
            write_sources(self.entries, self.root / "missing.asar", ["absent.node"])

    def test_rejects_truncated_and_invalid_archive_framing(self):
        archive = self.root / "bad.asar"
        for data in [b"", b"not an asar", struct.pack("<IIII", 4, 8, 4, 100)]:
            archive.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                header_hash(archive)


if __name__ == "__main__":
    unittest.main()
