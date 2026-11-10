"""Large resource snapshots must not prevent build-status diagnostics."""

from contextlib import nullcontext, redirect_stdout
import gzip
import hashlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from tools.ci.buildbuddy_log import profile_diagnostics, resource_diagnostics, frontend_diagnostics


class BuildBuddyLogTest(unittest.TestCase):
    def test_large_source_archive_metadata_does_not_relax_download_limit(self):
        size = 4 * 1024**3
        invocation = {'commitSha': 'a' * 40, 'repoUrl': 'https://github.com/formatjs/rules_electron',
                      'pattern': 'Source-built desktop example', 'success': True,
                      'invocationStatus': 'COMPLETE_INVOCATION_STATUS',
                      'artifacts': [{'name': 'electron-smoke-linux-x64.zip',
                                     'uri': 'bytestream://formatjs.buildbuddy.io/blobs/' + 'b' * 64 + '/' + str(size)}]}
        output = io.StringIO()
        with patch('tools.ci.buildbuddy_log.api_request') as request, redirect_stdout(output):
            profile_diagnostics(invocation, 'private-read-key', 'a' * 40)
        request.assert_not_called()
        self.assertIn('"size": ' + str(size), output.getvalue())
        from tools.ci.buildbuddy_artifacts import artifact_uri
        with self.assertRaisesRegex(ValueError, 'Invalid artifact digest or size'):
            artifact_uri({'invocation': [invocation]}, 'a' * 40, artifact_name='electron-smoke-linux-x64.zip')
        invocation['pattern'] = 'Cross-build Electron Apps'
        with self.assertRaisesRegex(ValueError, 'Invalid artifact digest or size'):
            profile_diagnostics(invocation, 'private-read-key', 'a' * 40)

    def test_frontend_metrics_verify_bytes_and_never_forward_unknown_fields(self):
        sample = {'elapsed_seconds': 2, 'cpu_cores': 2, 'rss_bytes': 4096, 'threads': 3,
                  'minor_faults': 4, 'major_faults': 1}
        for private in (False, True):
            payload = {**sample, **({'private-command': 'private-secret'} if private else {})}
            data = json.dumps(payload).encode() + b'\n'
            uri = 'bytestream://formatjs.buildbuddy.io/blobs/' + hashlib.sha256(data).hexdigest() + '/' + str(len(data))
            invocation = {'commitSha': 'a' * 40, 'repoUrl': 'https://github.com/formatjs/rules_electron',
                          'pattern': 'Source-built desktop example', 'success': False,
                          'invocationStatus': 'COMPLETE_INVOCATION_STATUS',
                          'artifacts': [{'name': 'source-frontend-metrics.jsonl', 'uri': uri}]}
            output = io.StringIO()
            with patch('tools.ci.buildbuddy_log.api_request', return_value=nullcontext(io.BytesIO(data))) as request:
                with redirect_stdout(output):
                    frontend_diagnostics(invocation, 'private-read-key', 'a' * 40)
            request.assert_called_once_with('GetFile', {'uri': uri}, 'private-read-key')
            self.assertNotIn('private', output.getvalue())
            if private:
                self.assertEqual(output.getvalue(), 'Source frontend metrics unavailable: INVALID_METRICS\n')
            else:
                summary = json.loads(output.getvalue().split(': ', 1)[1])
                self.assertEqual(summary['sampled_cpu_seconds'], 4)
                self.assertEqual(summary['sampled_peak_rss_bytes'], 4096)
                invocation['artifacts'][0]['uri'] = 'bytestream://formatjs.buildbuddy.io/blobs/' + '0' * 64 + '/' + str(len(data))
                with patch('tools.ci.buildbuddy_log.api_request', return_value=nullcontext(io.BytesIO(data))):
                    with self.assertRaisesRegex(ValueError, 'digest or size mismatch'):
                        frontend_diagnostics(invocation, 'private-read-key', 'a' * 40)

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

    def test_invalid_complete_profile_preserves_child_diagnostics_without_accepting_timings(self):
        profile = {'traceEvents': [{'ph': 'X', 'ts': 0, 'dur': 10**20,
                                   'name': 'private-command', 'cat': 'private-category'}]}
        output = self.source_profile(gzip.compress(json.dumps(profile).encode()))
        self.assertIn('"reason": "TIMING_LIMIT"', output)
        self.assertIn('BB child builds: []', output)
        self.assertNotIn('Verified BB profile', output)

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
