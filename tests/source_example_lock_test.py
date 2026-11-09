"""Source lock handoff binds actual bytes to the successful source build."""

import hashlib
import io
import json
import unittest
from unittest.mock import patch

from tools.ci.source_example_lock import ARTIFACT, MAX_BYTES, fetch_lock


class SourceExampleLockTest(unittest.TestCase):
    def response(self, data):
        self.uri = "bytestream://formatjs.buildbuddy.io/blobs/" + hashlib.sha256(data).hexdigest() + "/" + str(len(data))
        return {"invocation": [{
            "commitSha": "a" * 40, "repoUrl": "https://github.com/formatjs/rules_electron.git",
            "pattern": "Source-built desktop example", "success": True,
            "invocationStatus": "COMPLETE_INVOCATION_STATUS",
            "artifacts": [{"name": ARTIFACT, "uri": self.uri}],
        }]}

    def test_preserves_verified_lock_bytes(self):
        data = b'{"lockFileVersion":28,"registryFileHashes":{},"moduleExtensions":{}}\n'
        response = self.response(data)
        with patch("tools.ci.source_example_lock.api_request", return_value=io.BytesIO(data)) as request:
            self.assertEqual(fetch_lock(response, "a" * 40, "read-key"), data)
        request.assert_called_once_with("GetFile", {"uri": self.uri}, "read-key")

    def test_rejects_wrong_workflow_commit_or_incomplete_build_before_download(self):
        for field, value in (("pattern", "Cross-build Electron Apps"), ("commitSha", "b" * 40),
                             ("success", False), ("invocationStatus", "PARTIAL_INVOCATION_STATUS")):
            response = self.response(b"{}")
            response["invocation"][0][field] = value
            with self.subTest(field=field), patch("tools.ci.source_example_lock.api_request") as request:
                with self.assertRaises(ValueError):
                    fetch_lock(response, "a" * 40, "read-key")
                request.assert_not_called()

    def test_rejects_truncated_changed_or_oversized_artifact(self):
        data = b'{"lockFileVersion":28,"registryFileHashes":{},"moduleExtensions":{}}'
        for actual in (data[:-1], data + b"x", data.replace(b"28", b"29")):
            with self.subTest(actual=actual), patch("tools.ci.source_example_lock.api_request", return_value=io.BytesIO(actual)):
                with self.assertRaisesRegex(ValueError, "digest or size"):
                    fetch_lock(self.response(data), "a" * 40, "read-key")
        response = self.response(data)
        response["invocation"][0]["artifacts"][0]["uri"] = self.uri.rsplit("/", 1)[0] + "/" + str(MAX_BYTES + 1)
        with patch("tools.ci.source_example_lock.api_request") as request:
            with self.assertRaises(ValueError):
                fetch_lock(response, "a" * 40, "read-key")
            request.assert_not_called()

    def test_rejects_integrity_valid_non_lock_data(self):
        for lock in ([], {}, {"lockFileVersion": True, "registryFileHashes": {}, "moduleExtensions": {}},
                     {"lockFileVersion": 28, "registryFileHashes": [], "moduleExtensions": {}},
                     {"lockFileVersion": 28, "registryFileHashes": {}, "moduleExtensions": []}):
            data = json.dumps(lock).encode()
            with self.subTest(lock=lock), patch("tools.ci.source_example_lock.api_request", return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError):
                    fetch_lock(self.response(data), "a" * 40, "read-key")


if __name__ == "__main__":
    unittest.main()
