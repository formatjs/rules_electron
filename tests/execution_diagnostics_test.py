import unittest

from tools.ci.execution_diagnostics import failed_execution_lookups


class ExecutionDiagnosticsTest(unittest.TestCase):
    def test_only_failed_processes_and_rpc_errors_request_full_results(self):
        executions = [
            {"executionId": "success", "exitCode": 0},
            {"executionId": "running"},
            {"executionId": "compile-failure", "exitCode": 1},
            {"executionId": "rpc-failure", "status": {"code": 13}},
        ]
        self.assertEqual(failed_execution_lookups("invocation", executions), [
            {"invocation_id": "invocation", "execution_id": "compile-failure"},
            {"invocation_id": "invocation", "execution_id": "rpc-failure"},
        ])

    def test_digest_fallback_preserves_invocation_scope_and_rejects_missing_identity(self):
        digest = "ab" * 32
        self.assertEqual(failed_execution_lookups("invocation", [{"exitCode": 2, "actionDigest": {"hash": digest}}]), [
            {"invocation_id": "invocation", "action_digest_hash": digest},
        ])
        for execution in [{"exitCode": 1}, {"exitCode": 1, "actionDigest": {"hash": "invalid"}}]:
            with self.subTest(execution=execution), self.assertRaisesRegex(ValueError, "lacks lookup identity"):
                failed_execution_lookups("invocation", [execution])

    def test_large_successful_builds_only_expand_bounded_failure_details(self):
        executions = [{"executionId": str(index)} for index in range(10000)]
        executions += [{"executionId": f"failed-{index}", "exitCode": 1} for index in range(100)]
        lookups = failed_execution_lookups("invocation", executions)
        self.assertEqual(len(lookups), 32)
        self.assertEqual(lookups[-1], {"invocation_id": "invocation", "execution_id": "failed-31"})


if __name__ == "__main__":
    unittest.main()
