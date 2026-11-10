import gzip
import json
import unittest
import zlib

from tools.ci.profile_summary import decode_profile, recover_source_profile, summarize, summarize_source


class ProfileTest(unittest.TestCase):
    def test_recovered_source_metrics_count_bad_clock_events_without_forwarding_labels(self):
        profile = {'traceEvents': [
            {'ph': 'X', 'ts': 0, 'dur': 2000000, 'name': 'MerkleTreeComputer.buildForSpawn', 'cat': 'general information'},
            {'ph': 'X', 'ts': 0, 'dur': -10, 'name': 'private-event'},
            {'ph': 'X', 'ts': 2**62, 'dur': 100, 'name': 'private-event'},
            {'ph': 'X', 'ts': 0, 'dur': float('nan'), 'name': 'private-event'},
        ]}
        with self.assertRaises(ValueError):
            summarize_source(profile)
        summary = summarize_source(profile, allow_invalid_timings=True)
        self.assertEqual(summary['trace_span_seconds'], 2)
        self.assertEqual(summary['discarded_timing_events'], {'OUT_OF_RANGE': 2, 'NON_FINITE': 1})
        self.assertEqual(summary['operations']['MerkleTreeComputer.buildForSpawn']['count'], 1)
        self.assertNotIn('private-', json.dumps(summary))

    def test_truncated_source_profile_recovers_only_complete_events(self):
        event = {'ph': 'X', 'cat': 'action processing', 'name': 'private-path',
                 'ts': 0, 'dur': 2000000, 'args': {'mnemonic': 'CppCompile'}}
        prefix = '{"otherData":{"note":"traceEvents"},"traceEvents":[' + json.dumps(event)
        data = gzip.compress((prefix + ',{"name":"unfinished').encode())[:-8]
        with self.assertRaises(EOFError):
            decode_profile(data)
        recovered = recover_source_profile(data)
        self.assertEqual(recovered['traceEvents'], [event])
        summary = summarize_source(recovered)
        self.assertEqual(summary['actions']['CppCompile']['count'], 1)
        self.assertEqual(summary['trace_span_seconds'], 2)
        self.assertNotIn('private-', json.dumps(summary))

    def test_source_recovery_rejects_complete_corrupt_oversized_and_empty_streams(self):
        data = gzip.compress(b'{"traceEvents":[]}')
        with self.assertRaisesRegex(ValueError, 'truncated gzip'):
            recover_source_profile(data)
        corrupt = bytearray(data)
        corrupt[-8] ^= 1
        with self.assertRaises(zlib.error):
            recover_source_profile(corrupt)
        with self.assertRaisesRegex(ValueError, 'expanded size limit'):
            recover_source_profile(gzip.compress(b' ' * 100)[:-8], limit=10)
        with self.assertRaisesRegex(ValueError, 'no recoverable events'):
            recover_source_profile(data[:-8])

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

    def test_source_summary_distinguishes_remote_preparation_queue_and_execution(self):
        categories = ['Local parse to prepare for remote execution', 'Remote execution queuing time',
                      'Remote execution process wall time', 'action dependency checking']
        summary = summarize_source({'traceEvents': [
            {'ph': 'X', 'ts': 0, 'dur': 1000000, 'cat': category, 'name': 'private-command'}
            for category in categories
        ]})
        self.assertEqual(set(summary['categories']), set(categories))
        self.assertNotIn('private-', json.dumps(summary))

    def test_source_summary_reports_only_fixed_public_merkle_operation_names(self):
        summary = summarize_source({'traceEvents': [
            {'ph': 'X', 'ts': 0, 'dur': 1000000, 'cat': 'general information', 'name': name}
            for name in ['MerkleTreeComputer.buildForSpawn', 'acquiring semaphore', 'private-operation']
        ]})
        self.assertEqual(summary['operations'], {
            'MerkleTreeComputer.buildForSpawn': {'count': 1, 'cumulative_seconds': 1.0, 'max_seconds': 1.0},
            'acquiring semaphore': {'count': 1, 'cumulative_seconds': 1.0, 'max_seconds': 1.0},
        })
        self.assertNotIn('private-', json.dumps(summary))

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
