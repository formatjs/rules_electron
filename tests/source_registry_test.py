"""Pinned registry staging preserves every declared overlay byte."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.ci.stage_source_registry import restore_build_files, source_inputs, stage_registry


class SourceRegistryTest(unittest.TestCase):
    def test_real_overlay_restores_build_files_and_matches_all_integrities(self):
        source, pin = source_inputs()
        manifest = json.loads((source / "registry_build_files.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry"
            version = stage_registry(registry)
            self.assertEqual(version.name, pin["version"])
            descriptor = json.loads((version / "source.json").read_text())
            self.assertIn("source/BUILD.bazel", descriptor["overlay"])
            self.assertIn("tests/bcr/.bazelrc", descriptor["overlay"])
            for name, integrity in descriptor["overlay"].items():
                payload = (version / "overlay" / name).read_bytes()
                self.assertEqual(integrity, "sha256-" + base64.b64encode(hashlib.sha256(payload).digest()).decode())
            for name, contents in manifest.items():
                if name.startswith("bcr/overlay/") and name != "bcr/overlay/MODULE.bazel":
                    self.assertEqual((version / "overlay" / name.removeprefix("bcr/overlay/")).read_text(), contents)
                self.assertFalse((source / name).exists())
            original = (version / "source.json").read_bytes()
            with self.assertRaises(subprocess.CalledProcessError):
                stage_registry(registry)
            self.assertEqual((version / "source.json").read_bytes(), original)

    def test_build_manifest_cannot_escape_registry_or_replace_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("../BUILD.bazel", "/bcr/BUILD.bazel", "bcr/../BUILD.bazel",
                         "bcr//BUILD.bazel", "bcr/file.txt", "bcr\\BUILD.bazel"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    restore_build_files(root, {name: "invalid"})
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
