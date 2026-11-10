import copy
import io
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from tools.ci.buildbuddy_artifacts import artifact_uri, invocation_id, source_profile_uri
from tools.ci.run_native_smoke import extract_variant
from tools.ci.smoke_shards import SHARDS, archive_name


class ArtifactHandoffTest(unittest.TestCase):
    def response(self):
        return {"invocation": [{
            "commitSha": "a" * 40,
            "repoUrl": "https://github.com/formatjs/rules_electron.git",
            "pattern": "Cross-build Electron Apps",
            "success": True,
            "invocationStatus": "COMPLETE_INVOCATION_STATUS",
            "artifacts": [{"name": "electron-cross-smoke.zip", "uri": "bytestream://formatjs.buildbuddy.io/blobs/" + "b" * 64 + "/12"}],
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

    def test_source_workflow_artifacts_keep_exact_commit_and_completion_checks(self):
        response = self.response()
        response["invocation"][0]["pattern"] = "Source-built desktop example"
        self.assertEqual(artifact_uri(response, "a" * 40)[1:], ("b" * 64, 12))
        for field, value in [("commitSha", "c" * 40), ("success", False),
                             ("repoUrl", "https://github.com/example/other"),
                             ("invocationStatus", "PARTIAL_INVOCATION_STATUS")]:
            invalid = copy.deepcopy(response)
            invalid["invocation"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                artifact_uri(invalid, "a" * 40)

    def test_failed_source_profile_is_data_only_and_still_bound_to_terminal_commit(self):
        response = self.response()
        invocation = response['invocation'][0]
        invocation.update(pattern='Source-built desktop example', success=False)
        invocation['artifacts'][0]['name'] = 'cross-build-profile.json.gz'
        self.assertEqual(source_profile_uri(response, 'a' * 40, 'cross-build-profile.json.gz')[1:], ('b' * 64, 12))
        with self.assertRaises(ValueError):
            artifact_uri(response, 'a' * 40, artifact_name='cross-build-profile.json.gz')
        with self.assertRaises(ValueError):
            source_profile_uri(response, 'a' * 40, 'electron-cross-smoke.zip')
        for field, value in [('commitSha', 'c' * 40), ('repoUrl', 'https://github.com/example/private'),
                             ('pattern', 'Cross-build Electron Apps'), ('invocationStatus', 'PARTIAL_INVOCATION_STATUS')]:
            invalid = copy.deepcopy(response)
            invalid['invocation'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                source_profile_uri(invalid, 'a' * 40, 'cross-build-profile.json.gz')
        for uri in ['bytestream://untrusted.example/blobs/' + 'b' * 64 + '/12',
                    'bytestream://formatjs.buildbuddy.io/blobs/' + 'b' * 64 + '/' + str(64 * 1024**2 + 1)]:
            invalid = copy.deepcopy(response)
            invalid['invocation'][0]['artifacts'][0]['uri'] = uri
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                source_profile_uri(invalid, 'a' * 40, 'cross-build-profile.json.gz')

    def test_invocation_host_is_fixed_before_using_credentials(self):
        identifier = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(invocation_id("https://formatjs.buildbuddy.io/invocation/" + identifier), identifier)
        for host in ["https://untrusted.example", "http://formatjs.buildbuddy.io", "https://formatjs.buildbuddy.io@untrusted.example"]:
            with self.subTest(host=host), self.assertRaises(ValueError):
                invocation_id(host + "/invocation/" + identifier)

    def test_each_shard_requires_its_own_bound_artifact(self):
        response = self.response()
        artifacts = response["invocation"][0]["artifacts"]
        artifacts[:] = [{"name": archive_name(shard), "uri": "bytestream://formatjs.buildbuddy.io/blobs/" + str(index) * 64 + "/12"}
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
