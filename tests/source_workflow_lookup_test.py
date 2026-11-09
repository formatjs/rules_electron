"""Exact public workflow selection must not expose unrelated invocation data."""

import json
import unittest

from tools.ci.source_workflow_lookup import public_workflows


class SourceWorkflowLookupTest(unittest.TestCase):
    def test_only_exact_repository_commit_and_workflow_fields_escape(self):
        sha = "a" * 40
        row = {"repoUrl": "https://github.com/formatjs/electron.git", "commitSha": sha,
               "pattern": "Electron BCR consumer", "invocationId": "11111111-2222-3333-4444-555555555555",
               "invocationStatus": "PARTIAL_INVOCATION_STATUS", "success": False,
               "user": "private-user", "structuredCommandLine": "private-command"}
        unrelated = [dict(row, repoUrl="https://github.com/private/repository"),
                     dict(row, commitSha="b" * 40), dict(row, pattern="private-target")]
        rpc_row = dict(row, pattern=["Electron BCR consumer"])
        unrelated += [dict(row, pattern=[]), dict(row, pattern=["Electron BCR consumer", "private-target"])]
        selected = public_workflows([*unrelated, row, rpc_row], sha)
        self.assertEqual(selected, [{"id": row["invocationId"], "workflow": "Electron BCR consumer",
                                     "state": "running", "success": False}])
        self.assertNotIn("private", json.dumps(selected))

    def test_malformed_identifiers_and_commit_are_rejected(self):
        for sha in ("", "main", "a" * 39, "a" * 41):
            with self.subTest(sha=sha), self.assertRaisesRegex(ValueError, "Exact commit"):
                public_workflows([], sha)
        row = {"repoUrl": "https://github.com/formatjs/electron", "commitSha": "a" * 40,
               "pattern": "Electron source components", "invocationId": "private-invalid-id"}
        with self.assertRaisesRegex(ValueError, "Invalid workflow identifier"):
            public_workflows([row], "a" * 40)


if __name__ == "__main__":
    unittest.main()
