"""Reject accidental cross-platform input coupling and empty action queries."""

import json
from pathlib import Path
import tempfile
import unittest

from tools.ci.platform_inputs_audit import audit


class PlatformInputsAuditTest(unittest.TestCase):
    def test_transitive_inputs_and_packaged_entries_must_match_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = {
                "targets": [], "actions": [],
                "pathFragments": [{"id": 10, "label": "macos-update-smoke.cjs"}],
                "artifacts": [{"id": 20, "pathFragmentId": 10}],
                "depSetOfFiles": [{"id": 4, "directArtifactIds": [20]}],
            }
            entry = {"path": "Contents/Resources/app/macos-update-smoke.cjs"}
            for identifier, platform in enumerate(("linux", "macos", "windows"), 1):
                manifest = {"platform": platform, "entries": [entry] if platform == "macos" else []}
                (root / (platform + ".manifest.json")).write_text(json.dumps(manifest))
                graph["targets"].append({"id": identifier, "label": "//:" + platform + "_assembled"})
                graph["actions"].append({"mnemonic": "ElectronApp", "targetId": identifier,
                                         "arguments": [platform + ".manifest.json"], "inputDepSetIds": [identifier]})
                graph["depSetOfFiles"].append({"id": identifier, "transitiveDepSetIds": [4] if platform == "macos" else []})
            self.assertEqual(audit(graph, root), {"linux": 1, "macos": 1, "windows": 1})
            for platform in ("linux", "windows"):
                with self.subTest(platform=platform):
                    index = 1 if platform == "linux" else 3
                    graph["depSetOfFiles"][index]["transitiveDepSetIds"] = [4]
                    with self.assertRaisesRegex(ValueError, "macOS-only smoke input"):
                        audit(graph, root)
                    graph["depSetOfFiles"][index]["transitiveDepSetIds"] = []
            graph["depSetOfFiles"][0]["directArtifactIds"] = []
            with self.assertRaisesRegex(ValueError, "macOS-only smoke input"):
                audit(graph, root)
            graph["depSetOfFiles"][0]["directArtifactIds"] = [20]
            (root / "windows.manifest.json").write_text(json.dumps({"platform": "windows", "entries": [entry]}))
            with self.assertRaisesRegex(ValueError, "macOS-only smoke input"):
                audit(graph, root)

    def test_empty_query_cannot_report_success(self):
        with self.assertRaisesRegex(ValueError, "Expected Linux, macOS and Windows"):
            audit({}, Path("unused"))


if __name__ == "__main__":
    unittest.main()
