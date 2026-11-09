"""Public linker ownership survives redaction; unknown content stays private."""

import json
import unittest

from tools.ci.source_link_diagnostics import duplicate_definitions


class SourceLinkDiagnosticsTest(unittest.TestCase):
    def test_same_target_in_two_repositories_remains_distinguishable(self):
        log = """ld.lld: error: duplicate symbol: ui::Mixer(private_name)
>>> defined at mixer.cc:10 (../../ui/color/mixer.cc:10)
>>> bazel-out/bin/external/electron++electron+electron_ui_sources/libtarget_0123456789abcdef.lo(mixer.o)
>>> defined at mixer.cc:20 (../../electron/chromium_src/ui/color/mixer.cc:20)
>>> bazel-out/bin/external/electron++electron+electron_platform_sources/libtarget_0123456789abcdef.lo(mixer.o)
"""
        result = duplicate_definitions(log, {"ui/color/mixer.cc", "electron/chromium_src/ui/color/mixer.cc"},
                                       {"target_0123456789abcdef": "//ui/color:color"}, {"ui", "Mixer"})
        self.assertEqual(result, [{
            "identifiers": ["ui", "Mixer"],
            "definitions": [{"file": "ui/color/mixer.cc", "line": 10},
                            {"file": "electron/chromium_src/ui/color/mixer.cc", "line": 20}],
            "owners": [{"target": "//ui/color:color", "repository": "electron_ui_sources"},
                       {"target": "//ui/color:color", "repository": "electron_platform_sources"}],
        }])
        self.assertNotIn("private_name", json.dumps(result))
        self.assertNotIn("bazel-out", json.dumps(result))

    def test_unknown_symbols_paths_and_targets_are_not_reported(self):
        log = """ld.lld: error: duplicate symbol: private_symbol
>>> defined at private/path.cc:80
>>> private_repository/libtarget_aaaaaaaaaaaaaaaa.a(private.o)
"""
        self.assertEqual(duplicate_definitions(log, set(), {}, set()), [])

    def test_records_and_sites_are_bounded(self):
        definition = "\x1b[31mld.lld: error: duplicate symbol: known\x1b[0m\n"
        definition += "".join(">>> defined at public/file.cc:" + str(line) + "\n" for line in range(1, 50))
        result = duplicate_definitions(definition * 100, {"public/file.cc"}, {}, {"known"})
        self.assertEqual(len(result), 12)
        self.assertTrue(all(len(item["definitions"]) == 4 for item in result))


if __name__ == "__main__":
    unittest.main()
