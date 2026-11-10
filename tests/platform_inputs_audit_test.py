"""Reject accidental cross-platform input coupling and empty action queries."""

import json
import copy
from pathlib import Path
import tempfile
import unittest

from tools.ci.platform_inputs_audit import audit, audit_dmg_variants


class PlatformInputsAuditTest(unittest.TestCase):
    def test_dmg_variants_share_the_unlicensed_action_through_transitive_inputs(self):
        graph = {'actions': [
            {'mnemonic': 'ElectronDmg', 'outputIds': [10]},
            {'mnemonic': 'ElectronDmgLicense', 'outputIds': [20], 'inputDepSetIds': [2]},
            {'mnemonic': 'ElectronDmgLicense', 'outputIds': [21], 'inputDepSetIds': [3]},
        ], 'depSetOfFiles': [
            {'id': 1, 'directArtifactIds': [10]},
            {'id': 2, 'transitiveDepSetIds': [1]},
            {'id': 3, 'directArtifactIds': [10]},
        ]}
        self.assertEqual(audit_dmg_variants(graph), {'filesystem_actions': 1, 'license_actions': 2})
        changed = copy.deepcopy(graph)
        changed['depSetOfFiles'][2]['directArtifactIds'] = [20]
        with self.assertRaisesRegex(ValueError, 'same unlicensed filesystem image'):
            audit_dmg_variants(changed)
        changed = copy.deepcopy(graph)
        changed['actions'].append({'mnemonic': 'ElectronDmg', 'outputIds': [11]})
        with self.assertRaisesRegex(ValueError, 'one filesystem action'):
            audit_dmg_variants(changed)
        changed = copy.deepcopy(graph)
        changed['actions'].pop()
        with self.assertRaisesRegex(ValueError, 'two DMG license variants'):
            audit_dmg_variants(changed)
        with self.assertRaises(ValueError):
            audit_dmg_variants({})

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
