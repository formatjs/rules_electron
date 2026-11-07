import copy
import io
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from tools.ci.buildbuddy_artifacts import artifact_uri, invocation_id
from tools.ci.run_native_smoke import extract_variant


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

    def test_invocation_host_is_fixed_before_using_credentials(self):
        identifier = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(invocation_id("https://formatjs.buildbuddy.io/invocation/" + identifier), identifier)
        for host in ["https://untrusted.example", "http://formatjs.buildbuddy.io", "https://formatjs.buildbuddy.io@untrusted.example"]:
            with self.subTest(host=host), self.assertRaises(ValueError):
                invocation_id(host + "/invocation/" + identifier)

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


if __name__ == "__main__":
    unittest.main()
