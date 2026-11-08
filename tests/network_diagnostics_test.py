"""Network failures remain actionable without exposing log payloads."""

import json
import unittest

from tools.ci.network_diagnostics import network_diagnostics


class NetworkDiagnosticsTest(unittest.TestCase):
    def test_classifies_fetch_errors_without_forwarding_sensitive_text(self):
        log = ("Error downloading https://github.com/bazel-contrib/rules_python/releases/download/1.9.0/archive.tar.gz "
               "GET returned 504 Gateway Timeout; Read timed out\n"
               "Authorization: Bearer private-test-token\nhttps://private.invalid/internal?secret=test\n")
        report = network_diagnostics(log)
        self.assertEqual(report, {
            "categories": ["READ_TIMEOUT"], "http_status_codes": [504],
            "public_dependencies": ["bazel-contrib/rules_python"],
        })
        self.assertNotIn("private", json.dumps(report))
        self.assertNotIn("https://", json.dumps(report))

    def test_distinguishes_http_tls_dns_and_connect_failures(self):
        for log, expected in [
            ("Server returned HTTP response code: 403", {"http_status_codes": [403]}),
            ("SSLHandshakeException: PKIX path building failed", {"categories": ["TLS_FAILURE"]}),
            ("java.net.UnknownHostException", {"categories": ["DNS_FAILURE"]}),
            ("Connection timed out", {"categories": ["CONNECT_TIMEOUT"]}),
        ]:
            with self.subTest(log=log):
                report = network_diagnostics(log)
                self.assertEqual({key: value for key, value in report.items() if value}, expected)


if __name__ == "__main__":
    unittest.main()
