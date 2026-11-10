"""Large resource snapshots must not prevent build-status diagnostics."""

from contextlib import nullcontext, redirect_stdout
import gzip
import hashlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from tools.ci.buildbuddy_log import profile_diagnostics, resource_diagnostics


class BuildBuddyLogTest(unittest.TestCase):
    def source_profile(self, data, digest=None):
        invocation = {
            'commitSha': 'a' * 40, 'repoUrl': 'https://github.com/formatjs/rules_electron',
            'pattern': 'Source-built desktop example', 'success': False,
            'invocationStatus': 'COMPLETE_INVOCATION_STATUS',
            'artifacts': [{'name': 'cross-build-profile.json.gz',
                           'uri': 'bytestream://formatjs.buildbuddy.io/blobs/'
                           + (digest or hashlib.sha256(data).hexdigest()) + '/' + str(len(data))}],
        }
        output = io.StringIO()
        with patch('tools.ci.buildbuddy_log.api_request', return_value=nullcontext(io.BytesIO(data))) as request:
            with redirect_stdout(output):
                profile_diagnostics(invocation, 'private-read-key', 'a' * 40)
        request.assert_called_once()
        self.assertNotIn('private-', output.getvalue())
        return output.getvalue()

    def test_failed_source_profile_redacts_names_paths_and_unknown_mnemonics(self):
        profile = {'traceEvents': [
            {'ph': 'X', 'ts': 0, 'dur': 2000000, 'cat': 'action processing',
             'name': 'private-command', 'args': {'mnemonic': 'CppCompile', 'path': 'private-source'}},
            {'ph': 'X', 'ts': 2000000, 'dur': 1000000, 'cat': 'private-category',
             'name': 'private-command', 'args': {'mnemonic': 'private-mnemonic'}},
            {'ph': 'X', 'ts': 0, 'dur': 3000000, 'cat': 'general information', 'name': 'runExecutorMainPhase'},
        ]}
        output = self.source_profile(gzip.compress(json.dumps(profile).encode()))
        summary = json.loads(output.split('Verified BB profile cross-build-profile.json.gz: ', 1)[1].splitlines()[0])
        self.assertEqual(summary['trace_span_seconds'], 3)
        self.assertEqual(summary['actions']['CppCompile']['count'], 1)
        self.assertEqual(summary['categories']['other']['cumulative_seconds'], 1)
        self.assertEqual(summary['phases_seconds'], {'runExecutorMainPhase': 3})

    def test_failed_source_truncated_profile_reports_fixed_reason(self):
        data = gzip.compress(b'{"traceEvents": []}')[:-4]
        self.assertIn('"reason": "TRUNCATED_GZIP"', self.source_profile(data))
        self.assertIn('"reason": "NO_EVENTS"', self.source_profile(data))

    def test_recovered_source_profile_is_redacted_and_marked_incomplete(self):
        event = {'ph': 'X', 'ts': 0, 'dur': 1000000, 'cat': 'private-category',
                 'name': 'private-path', 'args': {'mnemonic': 'private-mnemonic'}}
        data = gzip.compress(('{"traceEvents":[' + json.dumps(event) + ',{"unfinished":').encode())[:-8]
        output = self.source_profile(data)
        self.assertIn('Recovered incomplete BB source profile', output)
        self.assertIn('"trace_span_seconds": 1.0', output)
        self.assertIn('"reason": "TRUNCATED_GZIP"', output)

    def test_failed_source_profile_still_requires_matching_digest(self):
        with self.assertRaisesRegex(ValueError, 'Profile digest or size mismatch'):
            self.source_profile(gzip.compress(b'{}'), digest='b' * 64)

    def summary(self, payload, max_bytes):
        output = io.StringIO()
        stream = io.BytesIO(payload)
        response = Mock()
        response.read.side_effect = stream.read
        with patch("tools.ci.buildbuddy_log.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = nullcontext(response)
            with redirect_stdout(output):
                resource_diagnostics("12345678-1234-1234-1234-123456789abc", "private-read-key", max_bytes=max_bytes)
        response.read.assert_called_once_with(max_bytes + 1)
        text = output.getvalue()
        self.assertNotIn("private-", text)
        return json.loads(text.removeprefix("BB tracked execution resources: "))

    def test_oversized_snapshot_reports_truncation_without_parsing_or_forwarding_body(self):
        result = self.summary(b"private-execution-metadata" * 10, 32)
        self.assertEqual(result, {"invocation_id": "12345678-1234-1234-1234-123456789abc",
                                  "truncated": True, "reason": "SIZE_LIMIT"})

    def test_bounded_snapshot_reports_actual_usage_without_backend_identifiers(self):
        payload = json.dumps({"execution": [{"stage": "COMPLETED", "worker": "private-worker", "executedActionMetadata": {
            "usageStats": {"cpuNanos": "500000000", "peakMemoryBytes": "4096"},
            "ioStats": {"fileDownloadSizeBytes": "22", "fileUploadSizeBytes": "33"},
        }}]}).encode()
        result = self.summary(payload, 1024)
        self.assertEqual(result["stages"], {"COMPLETED": 1})
        self.assertEqual(result["actions_with_usage"], 1)
        self.assertEqual(result["cpu_seconds"], 0.5)
        self.assertEqual(result["max_action_peak_memory_bytes"], 4096)
        self.assertEqual(result["worker_input_download_bytes"], 22)
        self.assertEqual(result["worker_output_upload_bytes"], 33)
        self.assertNotIn("truncated", result)


if __name__ == "__main__":
    unittest.main()
