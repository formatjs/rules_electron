"""Large resource snapshots must not prevent build-status diagnostics."""

from contextlib import nullcontext, redirect_stdout
import io
import json
import unittest
from unittest.mock import Mock, patch

from tools.ci.buildbuddy_log import resource_diagnostics


class BuildBuddyLogTest(unittest.TestCase):
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
