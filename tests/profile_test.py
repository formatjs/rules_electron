import gzip
import json
import unittest

from tools.ci.profile_summary import decode_profile, summarize, summarize_source


class ProfileTest(unittest.TestCase):
    def test_parallel_action_time_is_distinct_from_trace_span(self):
        profile = {"traceEvents": [
            {"ph": "M", "name": "thread_name", "tid": 0, "args": {"name": "Critical Path"}},
            {"ph": "X", "cat": "critical path component", "tid": 0, "ts": 0, "dur": 1000000},
            {"ph": "X", "cat": "action processing", "tid": 1, "ts": 0, "dur": 2000000, "args": {"mnemonic": "CppCompile"}},
            {"ph": "X", "cat": "action processing", "tid": 2, "ts": 0, "dur": 2000000, "args": {"mnemonic": "CppCompile"}},
            {"ph": "C", "name": "CPU", "ts": 99999999, "args": {"value": 5}},
            {"ph": "X", "cat": "general information", "name": "runAnalysisPhase", "ts": 0, "dur": 1000000},
        ]}
        result = summarize(decode_profile(gzip.compress(json.dumps(profile).encode())))
        self.assertEqual(result["trace_span_seconds"], 2)
        self.assertEqual(result["critical_path_seconds"], 1)
        self.assertEqual(result["phases_seconds"], {"runAnalysisPhase": 1})
        self.assertEqual(result["actions"]["CppCompile"], {"count": 2, "cumulative_seconds": 4, "max_seconds": 2})

    def test_empty_and_oversized_profiles_fail(self):
        with self.assertRaises(ValueError):
            summarize({"traceEvents": []})
        with self.assertRaises(ValueError):
            decode_profile(gzip.compress(b" " * 100), limit=10)

    def test_source_summary_keeps_metrics_without_trace_labels(self):
        result = summarize_source({"traceEvents": [
            {"ph": "X", "cat": "general information", "name": "runAnalysisPhase", "ts": 0, "dur": 2000000},
            {"ph": "X", "cat": "remote action cache check", "name": "/private/workspace/file", "ts": 0, "dur": 1000000},
            {"ph": "X", "cat": "custom category", "name": "custom label", "args": {"mnemonic": "custom command"}, "ts": 0, "dur": 1000000},
            {"ph": "X", "cat": "action processing", "args": {"mnemonic": "CppCompile"}, "ts": 0, "dur": 1000000},
        ]})
        self.assertEqual(result["phases_seconds"], {"runAnalysisPhase": 2})
        self.assertEqual(result["categories"]["remote action cache check"]["cumulative_seconds"], 1)
        self.assertEqual(result["categories"]["other"]["count"], 1)
        self.assertEqual(result["actions"]["CppCompile"]["count"], 1)
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("custom", json.dumps(result))
        for duration in [-1, float("nan"), 8 * 86400 * 1000000]:
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                summarize_source({"traceEvents": [{"ph": "X", "ts": 0, "dur": duration}]})


if __name__ == "__main__":
    unittest.main()
