import gzip
import json
import unittest

from tools.ci.profile_summary import decode_profile, summarize


class ProfileTest(unittest.TestCase):
    def test_parallel_action_time_is_distinct_from_trace_span(self):
        profile = {"traceEvents": [
            {"ph": "M", "name": "thread_name", "tid": 0, "args": {"name": "Critical Path"}},
            {"ph": "X", "cat": "critical path component", "tid": 0, "ts": 0, "dur": 1000000},
            {"ph": "X", "cat": "action processing", "tid": 1, "ts": 0, "dur": 2000000, "args": {"mnemonic": "CppCompile"}},
            {"ph": "X", "cat": "action processing", "tid": 2, "ts": 0, "dur": 2000000, "args": {"mnemonic": "CppCompile"}},
            {"ph": "C", "name": "CPU", "ts": 99999999, "args": {"value": 5}},
        ]}
        result = summarize(decode_profile(gzip.compress(json.dumps(profile).encode())))
        self.assertEqual(result["trace_span_seconds"], 2)
        self.assertEqual(result["critical_path_seconds"], 1)
        self.assertEqual(result["actions"]["CppCompile"], {"count": 2, "cumulative_seconds": 4, "max_seconds": 2})

    def test_empty_and_oversized_profiles_fail(self):
        with self.assertRaises(ValueError):
            summarize({"traceEvents": []})
        with self.assertRaises(ValueError):
            decode_profile(gzip.compress(b" " * 100), limit=10)


if __name__ == "__main__":
    unittest.main()
