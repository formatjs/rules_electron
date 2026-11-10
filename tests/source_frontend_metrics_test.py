"""Numeric-only frontend sampling, weighted CPU accounting and killed prefixes."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.ci.source_frontend_metrics import collect, parse_stat, summarize


class SourceFrontendMetricsTest(unittest.TestCase):
    def test_proc_fields_ignore_private_command_with_spaces_and_parentheses(self):
        state = parse_stat('99 (private command ) suffix) S 1 2 3 4 5 6 70 8 90 10 110 120 13 14 15 16 17 18 190 20 21', 4096)
        self.assertEqual(state, {'cpu_ticks': 230, 'start_ticks': 190, 'rss_bytes': 86016,
                                 'threads': 17, 'minor_faults': 70, 'major_faults': 90})
        self.assertNotIn('private', json.dumps(state))

    def test_interval_weighting_and_partial_last_record_do_not_expose_labels(self):
        first = {'elapsed_seconds': 2, 'cpu_cores': 1, 'rss_bytes': 4096, 'threads': 3,
                 'minor_faults': 4, 'major_faults': 1}
        second = {**first, 'elapsed_seconds': 5, 'cpu_cores': 3, 'rss_bytes': 8192, 'threads': 2}
        data = b''.join(json.dumps(value).encode() + b'\n' for value in (first, second))
        expected = {'samples': 2, 'recorded_seconds': 5, 'sampled_cpu_seconds': 11,
                    'average_cpu_cores': 2.2, 'max_cpu_cores': 3, 'sampled_peak_rss_bytes': 8192,
                    'max_threads': 3, 'minor_faults': 8, 'major_faults': 2, 'discarded_trailing_record': 0}
        self.assertEqual(summarize(data), expected)
        self.assertEqual(summarize(data + b'{"private-unfinished'), {**expected, 'discarded_trailing_record': 1})
        invalid = []
        for field, value in [('cpu_cores', float('nan')), ('cpu_cores', float('inf')),
                             ('cpu_cores', 10**400), ('cpu_cores', -1), ('rss_bytes', True),
                             ('elapsed_seconds', 0), ('threads', -1), ('private-command', 'secret')]:
            invalid.append({**first, field: value})
        for value in invalid:
            with self.subTest(fields=list(value)), self.assertRaises(ValueError):
                summarize(json.dumps(value).encode() + b'\n')
        with self.assertRaises(ValueError):
            summarize(data + json.dumps(first).encode() + b'\n')
        with self.assertRaises(ValueError):
            summarize(b' ' * (1024**2 + 1))

    def test_real_process_sampling_and_pid_reuse_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'metrics.jsonl'
            self.assertEqual(collect(os.getpid(), output, interval=0.01, max_samples=2), 2)
            result = summarize(output.read_bytes())
            self.assertEqual(result['samples'], 2)
            self.assertGreater(result['recorded_seconds'], 0)
            self.assertGreaterEqual(result['sampled_cpu_seconds'], 0)
            original = {'cpu_ticks': 100, 'start_ticks': 10, 'rss_bytes': 4096,
                        'threads': 1, 'minor_faults': 1, 'major_faults': 0}
            replaced = {**original, 'start_ticks': 11}
            with patch('tools.ci.source_frontend_metrics.read_process', side_effect=[original, replaced]), patch(
                    'tools.ci.source_frontend_metrics.time.sleep'):
                self.assertEqual(collect(123, output, max_samples=1), 0)
            self.assertEqual(output.read_bytes(), b'')


if __name__ == '__main__':
    unittest.main()
