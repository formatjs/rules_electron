import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from tools.ci.buildbuddy_artifacts import artifact_uri, invocation_id, smoke_status_context
from tools.ci.run_native_smoke import extract_variant
from tools.ci.smoke_shards import SHARDS, archive_name
from tools.ci.smoke_status_context import main as resolve_status


class ArtifactHandoffTest(unittest.TestCase):
    def test_status_command_keeps_credentials_and_unverified_metadata_private(self):
        environment = {'BUILDBUDDY_API_KEY': 'private-read-key', 'BUILD_SHA': 'a' * 40,
                       'INVOCATION_URL': 'https://app.buildbuddy.io/invocation/12345678-1234-1234-1234-123456789abc'}
        for trusted in (True, False):
            response = self.response()
            if not trusted:
                response['invocation'][0]['repoUrl'] = 'https://private.example/secret'
            output, errors = io.StringIO(), io.StringIO()
            with patch.dict('os.environ', environment, clear=True), patch(
                    'tools.ci.smoke_status_context.api_request', return_value=io.BytesIO(json.dumps(response).encode())) as request:
                with redirect_stdout(output), redirect_stderr(errors):
                    self.assertEqual(resolve_status(), 0 if trusted else 1)
            request.assert_called_once_with('GetInvocation', {'selector': {
                'invocation_id': '12345678-1234-1234-1234-123456789abc'}}, 'private-read-key')
            self.assertEqual(output.getvalue(), 'Native Electron Smoke\n' if trusted else '')
            self.assertEqual(errors.getvalue(), '' if trusted else 'SMOKE_STATUS_CONTEXT_FAILED\n')

    def test_status_context_uses_verified_workflow_not_dispatch_event(self):
        response = self.response()
        self.assertEqual(smoke_status_context(response, 'a' * 40), 'Native Electron Smoke')
        for field, value in [('success', False), ('commitSha', 'c' * 40), ('repoUrl', 'https://example.invalid/private'),
                             ('invocationStatus', 'PARTIAL_INVOCATION_STATUS'), ('pattern', 'Private workflow'), ('pattern', 'Source-built desktop example')]:
            invalid = copy.deepcopy(response)
            invalid['invocation'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                smoke_status_context(invalid, 'a' * 40)

    def response(self):
        return {"invocation": [{
            "commitSha": "a" * 40,
            "repoUrl": "https://github.com/perplexityai/rules_electron.git",
            "pattern": "Cross-build Electron Apps",
            "success": True,
            "invocationStatus": "COMPLETE_INVOCATION_STATUS",
            "artifacts": [{"name": "electron-cross-smoke.zip", "uri": "bytestream://remote.buildbuddy.io/blobs/" + "b" * 64 + "/12"}],
        }]}

    def test_artifacts_bind_to_successful_repository_commit(self):
        response = self.response()
        self.assertEqual(artifact_uri(response, "a" * 40)[1:], ("b" * 64, 12))
        for field, value in [("commitSha", "c" * 40), ("repoUrl", "https://github.com/example/other"),
                             ("success", False), ("pattern", "Other build"), ("invocationStatus", "PARTIAL_INVOCATION_STATUS")]:
            invalid = copy.deepcopy(response)
            invalid["invocation"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                artifact_uri(invalid, "a" * 40)
        response["invocation"][0]["artifacts"][0]["uri"] = "bytestream://untrusted.example/blobs/" + "b" * 64 + "/12"
        with self.assertRaises(ValueError):
            artifact_uri(response, "a" * 40)

    def test_prebuilt_shards_share_the_bounded_download_limit(self):
        response = self.response()
        artifact = response['invocation'][0]['artifacts'][0]
        for shard in SHARDS:
            artifact['name'] = archive_name(shard)
            for size in (2 * 1024**3, 2 * 1024**3 + 1):
                artifact['uri'] = 'bytestream://remote.buildbuddy.io/blobs/' + 'b' * 64 + '/' + str(size)
                with self.subTest(shard=shard, size=size):
                    if size <= 2 * 1024**3:
                        self.assertEqual(artifact_uri(response, 'a' * 40, artifact_name=artifact['name'])[2], size)
                    else:
                        with self.assertRaisesRegex(ValueError, 'Invalid artifact digest or size'):
                            artifact_uri(response, 'a' * 40, artifact_name=artifact['name'])

    def test_invocation_host_is_fixed_before_using_credentials(self):
        identifier = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(invocation_id("https://app.buildbuddy.io/invocation/" + identifier), identifier)
        for host in ["https://untrusted.example", "http://app.buildbuddy.io", "https://formatjs.buildbuddy.io", "https://app.buildbuddy.io@untrusted.example"]:
            with self.subTest(host=host), self.assertRaises(ValueError):
                invocation_id(host + "/invocation/" + identifier)

    def test_each_shard_requires_its_own_bound_artifact(self):
        response = self.response()
        artifacts = response["invocation"][0]["artifacts"]
        artifacts[:] = [{"name": archive_name(shard), "uri": "bytestream://remote.buildbuddy.io/blobs/" + str(index) * 64 + "/12"}
                        for index, shard in enumerate(SHARDS)]
        for index, shard in enumerate(SHARDS):
            self.assertEqual(artifact_uri(response, "a" * 40, artifact_name=archive_name(shard))[1], str(index) * 64)
        with self.assertRaises(ValueError):
            archive_name("../other")
        artifacts.pop()
        with self.assertRaisesRegex(ValueError, "one matching"):
            artifact_uri(response, "a" * 40, artifact_name=archive_name("windows-arm64"))

    def test_variant_extraction_rejects_escape_and_links(self):
        for name, mode in [("windows_x86_64_msvc/../../escape", 0o100644), ("windows_x86_64_msvc/app/link", 0o120777)]:
            content = io.BytesIO()
            with ZipFile(content, "w") as archive:
                info = ZipInfo(name)
                info.external_attr = mode << 16
                archive.writestr(info, b"data")
            with tempfile.TemporaryDirectory() as directory, ZipFile(content) as archive:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    extract_variant(archive, Path(directory), "windows_x86_64_msvc")
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_file_directory_collisions_fail_before_extracting(self):
        prefix = "windows_x86_64_msvc/app/"
        for names in (("cache", "cache/empty/"), ("cache", "cache/"), ("cache", "CACHE/empty/"), ("cache/", "CACHE/")):
            content = io.BytesIO()
            with ZipFile(content, "w") as archive:
                for name in names:
                    archive.writestr(prefix + name, b"" if name.endswith("/") else b"file")
            with tempfile.TemporaryDirectory() as directory, ZipFile(content) as archive:
                with self.subTest(names=names), self.assertRaises(ValueError):
                    extract_variant(archive, Path(directory), "windows_x86_64_msvc")
                self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
