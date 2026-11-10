"""Metadata handoff verifies identity and bytes without executing capture data."""

import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.ci.source_metadata import ARTIFACTS, download, main


class SourceMetadataTest(unittest.TestCase):
    def response(self):
        self.payloads = {}
        records = []
        for name in ARTIFACTS:
            data = ('verified bytes for ' + name).encode()
            uri = 'bytestream://formatjs.buildbuddy.io/blobs/' + hashlib.sha256(data).hexdigest() + '/' + str(len(data))
            self.payloads[uri] = data
            records.append({'name': 'capture/' + name, 'uri': uri})
        return {'invocation': [{'commitSha': 'a' * 40, 'repoUrl': 'https://github.com/formatjs/electron.git',
                                'pattern': 'Capture Linux ARM64 GN metadata', 'success': True,
                                'invocationStatus': 'COMPLETE_INVOCATION_STATUS', 'artifacts': records}]}

    def test_transfers_exact_allowlisted_bytes_and_refuses_existing_destination(self):
        response = self.response()
        response['invocation'][0]['artifacts'].append({'name': 'private-script', 'uri': 'private-store'})
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'capture'

            def request(method, body, key):
                self.assertEqual(method, 'GetFile')
                self.assertEqual(key, 'private-read-key')
                return io.BytesIO(self.payloads[body['uri']])

            with patch('tools.ci.source_metadata.api_request', side_effect=request) as api:
                self.assertEqual(download(response, 'a' * 40, 'private-read-key', output), sum(map(len, self.payloads.values())))
                self.assertEqual(api.call_count, len(ARTIFACTS))
                self.assertEqual({path.name for path in output.iterdir()}, set(ARTIFACTS))
                for item in response['invocation'][0]['artifacts'][:-1]:
                    self.assertEqual((output / Path(item['name']).name).read_bytes(), self.payloads[item['uri']])
                with self.assertRaises(FileExistsError):
                    download(response, 'a' * 40, 'private-read-key', output)
                self.assertEqual(api.call_count, len(ARTIFACTS))

    def test_identity_duplicates_missing_store_and_size_fail_before_file_download(self):
        response = self.response()
        invalids = []
        for field, value in [('commitSha', 'b' * 40), ('repoUrl', 'https://github.com/formatjs/rules_electron'),
                             ('pattern', 'Electron source components'), ('success', False),
                             ('invocationStatus', 'PARTIAL_INVOCATION_STATUS')]:
            invalid = copy.deepcopy(response)
            invalid['invocation'][0][field] = value
            invalids.append(invalid)
        for change in ('missing', 'duplicate', 'store', 'size'):
            invalid = copy.deepcopy(response)
            rows = invalid['invocation'][0]['artifacts']
            if change == 'missing':
                rows.pop()
            elif change == 'duplicate':
                rows.append(copy.deepcopy(rows[0]))
            elif change == 'store':
                rows[0]['uri'] = rows[0]['uri'].replace('formatjs.buildbuddy.io', 'private.invalid')
            else:
                rows[0]['uri'] = 'bytestream://formatjs.buildbuddy.io/blobs/' + 'b' * 64 + '/' + str(64 * 1024**2 + 1)
            invalids.append(invalid)
        for invalid in invalids:
            with tempfile.TemporaryDirectory() as temporary, patch('tools.ci.source_metadata.api_request') as request:
                with self.assertRaises(ValueError):
                    download(invalid, 'a' * 40, 'private-read-key', Path(temporary) / 'capture')
                request.assert_not_called()

    def test_changed_truncated_and_oversized_bodies_are_not_promoted(self):
        response = self.response()
        original = next(iter(self.payloads.values()))
        for actual in (original[:-1], b'x' * len(original), original + b'x'):
            with self.subTest(size=len(actual)), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'capture'
                with patch('tools.ci.source_metadata.api_request', return_value=io.BytesIO(actual)):
                    with self.assertRaises(ValueError):
                        download(response, 'a' * 40, 'private-read-key', output)
                self.assertFalse((output / 'linux-arm64-graph.json.gz').exists())

    def test_command_failure_never_echoes_private_metadata_or_credentials(self):
        response = self.response()
        response['invocation'][0]['repoUrl'] = 'https://private.example/implementation'
        environment = {'BUILDBUDDY_API_KEY': 'private-read-key', 'BUILD_SHA': 'a' * 40,
                       'INVOCATION_URL': 'https://formatjs.buildbuddy.io/invocation/12345678-1234-1234-1234-123456789abc'}
        errors = io.StringIO()
        with patch.dict('os.environ', environment, clear=True), patch('tools.ci.source_metadata.api_request',
                return_value=io.BytesIO(json.dumps(response).encode())), redirect_stderr(errors):
            self.assertEqual(main(), 1)
        self.assertEqual(errors.getvalue(), 'SOURCE_METADATA_HANDOFF_FAILED\n')


if __name__ == '__main__':
    unittest.main()
