"""CI credentials follow event trust and the actual checkout."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from python.runfiles import runfiles


class CiBazelTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".bazelversion").write_text("9.3.1\n")
        self.bazel = self.root / "bazel-real"
        self.bazel.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        self.bazel.chmod(0o755)
        git = self.root / "git"
        git.write_text('#!/bin/sh\nprintf "%s\\n" "$CHECKOUT_SHA"\n')
        git.chmod(0o755)
        files = runfiles.Create()
        self.wrapper = files.Rlocation(files.CurrentRepository() + "/tools/ci/bazel.sh")
        self.environment = dict(
            os.environ,
            PATH=str(self.root) + os.pathsep + os.environ["PATH"],
            BAZEL_REAL=str(self.bazel),
            GITHUB_WORKSPACE=str(self.root),
            GITHUB_EVENT_NAME="push",
            GITHUB_REF="refs/heads/main",
            GITHUB_REPOSITORY="perplexityai/rules_electron",
            GITHUB_SHA="a" * 40,
            CHECKOUT_SHA="a" * 40,
            GITHUB_RUN_ID="1234",
            GITHUB_RUN_ATTEMPT="2",
            BB_RO_KEY="public-key",
            BB_RW_KEY="writer-key",
        )

    def invoke(self, *args, **environment):
        return subprocess.run(
            ["bash", self.wrapper, *args],
            env=self.environment | environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_untrusted_events_and_overridden_checkouts_never_get_writer(self):
        for environment in [
            {"GITHUB_EVENT_NAME": "pull_request"},
            {"GITHUB_EVENT_NAME": "pull_request_target"},
            {"GITHUB_EVENT_NAME": "merge_group"},
            {"GITHUB_EVENT_NAME": "workflow_dispatch"},
            {"GITHUB_REF": "refs/heads/feature"},
            {"GITHUB_REPOSITORY": "other/rules_electron"},
            {"CHECKOUT_SHA": "b" * 40},
        ]:
            with self.subTest(environment=environment):
                result = self.invoke("test", "//...", **environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = result.stdout.splitlines()
                self.assertIn("--remote_header=x-buildbuddy-api-key=public-key", args)
                self.assertIn("--bes_header=x-buildbuddy-api-key=public-key", args)
                self.assertIn("--noremote_upload_local_results", args)
                self.assertNotIn("writer-key", result.stdout + result.stderr)
                self.assertNotIn("--remote_upload_local_results", args)

    def test_exact_main_push_uses_writer_for_remote_and_events(self):
        result = self.invoke("build", "//tests:app")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.splitlines()
        self.assertIn("--remote_header=x-buildbuddy-api-key=writer-key", args)
        self.assertIn("--bes_header=x-buildbuddy-api-key=writer-key", args)
        self.assertIn("--remote_upload_local_results", args)
        self.assertNotIn("--noremote_upload_local_results", args)

    def test_missing_keys_fail_before_bazel_without_disclosing_credentials(self):
        for environment in [
            {"BB_RW_KEY": ""},
            {"BB_RO_KEY": "", "GITHUB_EVENT_NAME": "pull_request"},
        ]:
            with self.subTest(environment=environment):
                result = self.invoke("test", "//...", **environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("writer-key", result.stderr)
                self.assertNotIn("public-key", result.stderr)

    def test_startup_and_run_arguments_keep_their_positions(self):
        result = self.invoke("--host_jvm_args=-Xmx4g", "run", "//:tool", "--", "two words")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.splitlines()
        self.assertEqual(args[:2], ["--host_jvm_args=-Xmx4g", "run"])
        self.assertEqual(args[-3:], ["//:tool", "--", "two words"])

    def test_info_does_not_require_credentials_or_build_flags(self):
        result = self.invoke("info", "server_pid", BB_RO_KEY="", BB_RW_KEY="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["info", "server_pid"])


if __name__ == "__main__":
    unittest.main()
