"""Fatal checks survive noisy startup logs without exporting unknown content."""

import json
import unittest

from tools.ci.source_runtime_diagnostics import runtime_failures


class RuntimeDiagnosticsTest(unittest.TestCase):
    def test_fatal_check_precedes_repeated_dbus_errors(self):
        noise = "ERROR public/bus.cc:408 connection private_host\n"
        log = noise * 20 + "FATAL private/path/check.h:71 Check failed: known private_secret\n"
        self.assertEqual(runtime_failures(log, {"bus.cc", "check.h"}, {"ERROR", "FATAL", "Check", "failed", "known"}), {
            "public_check_sites": [{"file": "check.h", "line": 71}, {"file": "bus.cc", "line": 408}],
            "public_fatal_identifiers": [["FATAL", "Check", "failed", "known"], ["ERROR"]],
        })

    def test_javascript_exception_precedes_startup_noise(self):
        log = "ERROR bus.cc:408 connection\n" * 20 + "TypeError: known private_value\n"
        result = runtime_failures(log, {"bus.cc"}, {"ERROR", "TypeError", "known"})
        self.assertEqual(result["public_fatal_identifiers"][0], ["TypeError", "known"])
        self.assertNotIn("private_value", json.dumps(result))

    def test_output_caps_and_unknown_names(self):
        log = "\x1b[31mFATAL private.cc:25 private_secret\x1b[0m\n"
        log += "FATAL known.cc:0 private_secret\nFATAL known.cc:10000 private_secret\n"
        log += "".join("FATAL known.cc:" + str(index) + " known_" + str(index) + "\n" for index in range(1, 30))
        result = runtime_failures(log, {"known.cc"}, {"known_" + str(index) for index in range(1, 30)})
        self.assertEqual(result["public_check_sites"], [{"file": "known.cc", "line": index} for index in range(1, 9)])
        self.assertEqual(result["public_fatal_identifiers"], [["known_" + str(index)] for index in range(1, 7)])


if __name__ == "__main__":
    unittest.main()
