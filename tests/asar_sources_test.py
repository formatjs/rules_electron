"""Standalone ASAR layout, deterministic bytes and rejected source mappings."""

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_links_share_payload_resolve_chains_and_keep_reproducibility(self):
        archive = self.root / "links.asar"
        links = {"entry.cjs": "module.cjs", "chain.cjs": "entry.cjs", "assets-link": "assets",
                 "root-link": "", "message-link": "assets-link/message.txt"}
        digest = write_sources(self.entries, archive, ["assets/message.txt"], links)
        data = archive.read_bytes()
        _, header_size, _, length = struct.unpack_from("<IIII", data)
        files = json.loads(data[16:16 + length])["files"]
        self.assertEqual(files["chain.cjs"], {"link": "module.cjs"})
        self.assertEqual(files["assets-link"], {"link": "assets"})
        self.assertEqual(files["message-link"], {"link": "assets/message.txt"})
        self.assertEqual(files["root-link"], {"link": ""})
        self.assertEqual(data[8 + header_size:], self.module.read_bytes())
        self.assertEqual((Path(str(archive) + ".unpacked") / "assets/message.txt").read_bytes(),
                         (self.tree / "message.txt").read_bytes())
        second = self.root / "links-again.asar"
        self.assertEqual(write_sources(list(reversed(self.entries)), second, ["assets/message.txt"],
                                       dict(reversed(list(links.items())))), digest)
        self.assertEqual(second.read_bytes(), data)

    def test_rejects_link_cycles_collisions_missing_and_escaping_targets(self):
        cases = [{"module.cjs": "assets"}, {"alias": "assets", "alias/child": "module.cjs"},
                 {"alias": "missing"}, {"a": "b", "b": "a"}, {"a": "a/child"},
                 {"a": "assets/a", "assets/a": "a"}, {"/alias": "module.cjs"},
                 {"alias": "../module.cjs"}, {"alias": "assets/./message.txt"}]
        for links in cases:
            with self.subTest(links=links), self.assertRaises(ValueError):
                write_sources(self.entries, self.root / "bad-links.asar", symlinks=links)
        self.assertFalse((self.root / "bad-links.asar").exists())
        self.assertFalse((self.root / "bad-links.asar.unpacked").exists())

    def test_patterns_require_declared_tool_and_reject_invalid_tool_results(self):
        archive = self.root / "patterns.asar"
        with self.assertRaisesRegex(ValueError, "require file_matcher"):
            write_sources(self.entries, archive, unpacked_patterns=["**/*.cjs"])
        tool = {"node": "declared-node", "script": "declared-script", "modules": "declared-modules"}
        for result in [["../escape"], ["absent.cjs"], ["module.cjs", "module.cjs"], [1], "invalid"]:
            with self.subTest(result=result), patch("electron.private.matching.subprocess.run",
                                                   return_value=SimpleNamespace(stdout=json.dumps(result))):
                with self.assertRaisesRegex(ValueError, "undeclared or duplicate"):
                    write_sources(self.entries, archive, unpacked_patterns=["**/*.cjs"], file_matcher=tool)
        self.assertFalse(archive.exists())
        self.assertFalse(Path(str(archive) + ".unpacked").exists())

    def test_rejects_truncated_and_invalid_archive_framing(self):
        archive = self.root / "bad.asar"
        for data in [b"", b"not an asar", struct.pack("<IIII", 4, 8, 4, 100)]:
            archive.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                header_hash(archive)


if __name__ == "__main__":
    unittest.main()
