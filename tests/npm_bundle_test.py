"""Verify real bundled bytes, ownership and pruning from a pinned npm archive."""

import json
import hashlib
from pathlib import Path
import sys
import unittest

OMITTED = "node_modules/npm/node_modules/@isaacs/cliui/node_modules/ansi-regex"


class NpmBundleTest(unittest.TestCase):
    def test_bundled_package_uses_verified_owner_and_preserves_module_bytes(self):
        parent = json.loads((TREE / "npm/package.json").read_text())
        child = json.loads((TREE / "npm/node_modules/semver/package.json").read_text())
        self.assertEqual((parent["version"], child["name"], child["version"]), ("11.4.2", "semver", "7.7.2"))
        self.assertEqual(hashlib.sha256((TREE / "npm/node_modules/semver/functions/valid.js").read_bytes()).hexdigest(),
                         "0de7ea736cb7807179d46dfac09c830a9338e02b6a07db12d7040cde2def6025")
        provenance = json.loads(PROVENANCE.read_text())
        lock = json.loads(LOCK.read_text())["packages"]
        self.assertEqual(set(provenance), set(lock) - {"", "node_modules/npm", OMITTED})
        for path, entry in provenance.items():
            self.assertEqual(entry["owner"], "node_modules/npm")
            self.assertEqual(entry["integrity"], lock["node_modules/npm"]["integrity"])
            actual = json.loads((TREE / path.removeprefix("node_modules/") / "package.json").read_text())
            self.assertEqual(actual["version"], lock[path]["version"])

    def test_locked_development_bundle_is_absent_from_runtime(self):
        self.assertNotIn(OMITTED, json.loads(PROVENANCE.read_text()))
        self.assertFalse((TREE / OMITTED.removeprefix("node_modules/")).exists())
        self.assertTrue((TREE / "npm/node_modules/@isaacs/cliui/package.json").is_file())


if __name__ == "__main__":
    TREE, PROVENANCE, LOCK = [Path(sys.argv.pop(1)) for _ in range(3)]
    unittest.main()
