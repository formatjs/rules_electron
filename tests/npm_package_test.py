"""Workspace package trees and manifests use the same declared bytes."""

import json
from pathlib import Path
import sys
import struct
import tempfile
import unittest

from electron.private.npm_package import create_package


class NpmPackageTest(unittest.TestCase):
    def test_bazel_package_provider_reaches_tree_and_app_manifest(self):
        tree = TREE / "@example/workspace"
        package = json.loads((tree / "package.json").read_text())
        self.assertEqual(package["name"], "@example/workspace")
        self.assertEqual(package["version"], "4.5.6")
        self.assertEqual((tree / "index.cjs").read_bytes(), SOURCE.read_bytes())
        self.assertEqual(json.loads(APP_MANIFEST.read_text())["dependencies"], {"@example/workspace": "4.5.6"})
        nested = TREE / "@example/workspace/node_modules/alias"
        self.assertEqual(json.loads((nested / "package.json").read_text())["name"], "@example/workspace")
        self.assertEqual((nested / "index.cjs").read_bytes(), SOURCE.read_bytes())
        data = ASAR.read_bytes()
        length = struct.unpack_from("<I", data, 12)[0]
        package_header = json.loads(data[16:16 + length])["files"]["@example"]["files"]["workspace"]["files"]
        self.assertEqual(package_header["assets"]["files"]["nested"]["files"]["empty"], {"files": {}})

    def test_package_normalization_tracks_empty_directories_and_production_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, dependency = root / "source.json", root / "dependency.json"
            original = {"name": "@example/parent", "version": "1.2.3", "dependencies": {"child": "workspace:*"},
                        "scripts": {"postinstall": "never executed"}}
            source.write_text(json.dumps(original))
            dependency.write_text('{"name":"child","version":"2.0.0"}')
            manifest, directories = root / "package.json", root / "directories.json"
            assets = root / "assets"
            (assets / "empty").mkdir(parents=True)
            entries = [{"source": str(SOURCE), "path": "index.cjs"}, {"source": str(assets), "path": "assets", "directory": True}]
            create_package(source, entries, root / "package", manifest, directories,
                           dependency_manifests=[dependency], remove_scripts=True)
            self.assertEqual((root / "package/package.json").read_bytes(), manifest.read_bytes())
            self.assertEqual(json.loads(manifest.read_text()), {"name": "@example/parent", "version": "1.2.3", "dependencies": {"child": "2.0.0"}})
            self.assertEqual(json.loads(source.read_text()), original)
            self.assertEqual(json.loads(directories.read_text()), ["assets/empty"])
            self.assertTrue((root / "package/assets/empty").is_dir())
            second_manifest, second_directories = root / "second.json", root / "second-directories.json"
            create_package(source, list(reversed(entries)), root / "second", second_manifest, second_directories,
                           dependency_manifests=[dependency], remove_scripts=True)
            self.assertEqual(manifest.read_bytes(), second_manifest.read_bytes())
            self.assertEqual(directories.read_bytes(), second_directories.read_bytes())
            self.assertEqual((root / "package/index.cjs").read_bytes(), (root / "second/index.cjs").read_bytes())
            for invalid in ([], {"version": "1.0.0"}, {"name": "package", "version": "1.2"}):
                source.write_text(json.dumps(invalid))
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    create_package(source, [], root / "bad", root / "bad.json", root / "bad-directories.json")
            self.assertFalse((root / "bad").exists())
            source.write_text('{"name":"package","version":"1.0.0"}')
            for path in ("package.json", "../escape"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    create_package(source, [{"source": str(SOURCE), "path": path}], root / "collision",
                                   root / "collision.json", root / "collision-directories.json")
            self.assertFalse((root / "collision").exists())


if __name__ == "__main__":
    TREE, APP_MANIFEST, SOURCE, ASAR = [Path(sys.argv.pop(1)) for _ in range(4)]
    unittest.main()
