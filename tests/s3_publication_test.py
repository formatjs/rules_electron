"""Check AWS vectors and the public release command against a verifying server."""

from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlsplit
from xml.etree import ElementTree as ET

from electron.private.update import create_feed
from electron.tools.publish_s3 import MAX_OBJECT, MIN_PART, S3Publisher, signed_headers

TOOL = Path(sys.argv.pop(1)).resolve()
ACCESS = 'FIXTUREACCESSKEY'
SECRET = 'fixture/secret+key='
TOKEN = 'fixture/session+token='
PREFIX = '/bucket/release%20prefix//'


def authorized(request, body):
    match = re.fullmatch(r'AWS4-HMAC-SHA256 Credential=' + ACCESS
                        + r'/(\d{8})/us-west-2/s3/aws4_request,SignedHeaders=([^,]+),Signature=([0-9a-f]{64})',
                        request.headers.get('Authorization', ''))
    if not match:
        return False
    date, signed, signature = match.groups()
    names = signed.split(';')
    url = urlsplit(request.path)
    query = parse_qs(url.query, keep_blank_values=True)
    required = {'host', 'x-amz-date', 'x-amz-content-sha256', 'x-amz-security-token'}
    if request.command == 'PUT' or request.command == 'POST' and 'uploadId' in query:
        required.update({'content-length', 'content-type'})
        if request.command != 'PUT' or 'uploadId' not in query:
            required.add('if-match' if request.headers.get('If-Match') else 'if-none-match')
    if names != sorted(set(names)) or not required.issubset(names):
        return False
    timestamp = request.headers['x-amz-date']
    if (timestamp[:8] != date or request.headers['x-amz-security-token'] != TOKEN
            or request.headers['x-amz-content-sha256'] != hashlib.sha256(body).hexdigest()
            or abs((datetime.now(timezone.utc) - datetime.strptime(timestamp, '%Y%m%dT%H%M%SZ')
                    .replace(tzinfo=timezone.utc)).total_seconds()) > 120):
        return False
    canonical_query = '&'.join(key + '=' + value for key, value in sorted(
        (quote(key, safe='-._~'), quote(value, safe='-._~')) for key, value in parse_qsl(url.query, keep_blank_values=True)))
    canonical = request.command + '\n' + url.path + '\n' + canonical_query + '\n'
    canonical += ''.join(name + ':' + ' '.join(request.headers[name].split()) + '\n' for name in names)
    canonical += '\n' + signed + '\n' + hashlib.sha256(body).hexdigest()
    scope = date + '/us-west-2/s3/aws4_request'
    message = 'AWS4-HMAC-SHA256\n' + timestamp + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()
    key = ('AWS4' + SECRET).encode()
    for part in [date, 'us-west-2', 's3', 'aws4_request']:
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(signature, hmac.new(key, message.encode(), hashlib.sha256).hexdigest())


class S3PublicationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        package = self.root / 'package.json'
        package.write_text('{"version":"2.0.0"}')
        artifact = self.root / 'artifact'
        artifact.write_bytes(bytes(range(256)) * 600)
        self.name = 'Sample Setup 世界.exe'
        self.feed = self.root / 'feed'
        create_feed(artifacts=[{'source': artifact, 'name': self.name}], package_json=package,
                    output=self.feed, platform='windows', architecture='arm64',
                    release_date='2026-01-02T03:04:05Z', blockmaps=[self.name])
        self.objects, self.requests = {}, []
        self.redirect, self.race, self.conflict = False, False, False
        self.uploads, self.aborted, self.multipart_mode, self.extra_args = {}, [], None, []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                url = urlsplit(self.path)
                name = unquote(url.path[len(PREFIX):])
                query = parse_qs(url.query, keep_blank_values=True)
                valid = authorized(self, body) and self.path.startswith(PREFIX)
                owner.requests.append((self.command, name, valid))
                status, reply, etag = 200, b'', None
                if not valid:
                    status = 403
                elif owner.redirect:
                    status = 307
                elif self.command == 'HEAD':
                    status = 200 if name in owner.objects else 404
                elif self.command == 'GET':
                    status = 200 if name in owner.objects else 404
                    reply = owner.objects.get(name, b'')
                elif self.command == 'POST' and query == {'uploads': ['']}:
                    identifier = 'fixture+upload/id=' + str(len(owner.requests))
                    owner.uploads[identifier] = {'name': name, 'parts': {}}
                    reply = ('<InitiateMultipartUploadResult><UploadId>' + identifier
                             + '</UploadId></InitiateMultipartUploadResult>').encode()
                elif 'uploadId' in query:
                    identifier = query['uploadId'][0]
                    upload = owner.uploads.get(identifier)
                    if not upload or upload['name'] != name:
                        status = 404
                    elif self.command == 'DELETE':
                        del owner.uploads[identifier]
                        owner.aborted.append(identifier)
                        status = 204
                    elif self.command == 'PUT':
                        number = int(query['partNumber'][0])
                        if owner.multipart_mode == 'part_failure' and number == 2:
                            status = 503
                        else:
                            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
                            upload['parts'][number] = (body, etag)
                    elif self.command == 'POST':
                        parts = ET.fromstring(body)
                        actual = [(int(entry[0].text), entry[1].text) for entry in parts]
                        expected = [(number, value[1]) for number, value in sorted(upload['parts'].items())]
                        if actual != expected or [number for number, _ in actual] != list(range(1, len(actual) + 1)):
                            status = 400
                        elif owner.multipart_mode == 'embedded_error':
                            reply = b'<Error><Code>InternalError</Code></Error>'
                        elif owner.multipart_mode == 'completion_conflict':
                            status = 409
                        elif self.headers.get('If-None-Match') != '*':
                            status = 400
                        elif name in owner.objects:
                            status = 412
                        else:
                            owner.objects[name] = b''.join(upload['parts'][number][0] for number, _ in actual)
                            del owner.uploads[identifier]
                            reply = b'<CompleteMultipartUploadResult><ETag>"complete"</ETag></CompleteMultipartUploadResult>'
                elif owner.conflict:
                    status = 409
                elif name == 'latest.yml' and owner.race:
                    owner.objects[name] = b'concurrent release'
                    status = 412
                elif ((self.headers.get('If-None-Match') == '*' and name in owner.objects)
                      or (name in owner.objects and self.headers.get('If-Match') != '"fixture-etag"')):
                    status = 412
                else:
                    owner.objects[name] = body
                self.send_response(status)
                self.send_header('Content-Length', str(len(reply)))
                if status == 200 and name == 'latest.yml':
                    self.send_header('ETag', '"fixture-etag"')
                elif etag:
                    self.send_header('ETag', etag)
                if owner.redirect:
                    self.send_header('Location', owner.url + 'credential-target')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(reply)

            do_HEAD = do_GET = do_PUT = do_POST = do_DELETE = handle_request

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = 'http://127.0.0.1:' + str(server.server_port) + PREFIX

    def publish(self, success=True, secret=SECRET):
        result = subprocess.run([
            str(TOOL), '--feed', str(self.feed), '--channel', 'latest.yml', '--destination', self.url,
            '--region', 'us-west-2', '--allow-http-loopback', '--access-key-env', 'FIXTURE_ACCESS',
            '--secret-key-env', 'FIXTURE_SECRET', '--session-token-env', 'FIXTURE_TOKEN',
        ] + self.extra_args, env={**os.environ, 'FIXTURE_ACCESS': ACCESS, 'FIXTURE_SECRET': secret, 'FIXTURE_TOKEN': TOKEN},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        for value in (ACCESS, SECRET, TOKEN, secret):
            self.assertNotIn(value.encode(), result.stdout + result.stderr)
        self.assertEqual(result.stdout if success else result.stderr,
                         b'S3_UPDATE_PUBLISHED\n' if success else b'S3_UPDATE_PUBLICATION_FAILED\n')

    def test_signed_uploads_channel_promotion_and_identical_retry(self):
        self.publish()
        expected = {path.name: path.read_bytes() for path in self.feed.iterdir()}
        self.assertEqual(self.objects, expected)
        self.assertEqual(self.requests, [('HEAD', 'latest.yml', True), ('PUT', self.name, True),
                                        ('PUT', self.name + '.blockmap', True), ('PUT', 'latest.yml', True)])
        self.requests.clear()
        self.publish()
        self.assertEqual(self.objects, expected)
        self.assertTrue(all(valid for _, _, valid in self.requests))
        self.assertEqual([name for method, name, _ in self.requests if method == 'GET'],
                         [self.name, self.name + '.blockmap'])

    def test_race_and_retryable_conflict_never_overwrite_channel(self):
        self.objects['latest.yml'] = b'old channel'
        self.conflict = True
        self.publish(False)
        self.assertEqual(self.objects, {'latest.yml': b'old channel'})
        self.conflict, self.race = False, True
        self.publish(False)
        self.assertEqual(self.objects['latest.yml'], b'concurrent release')
        self.race = False
        self.publish()

    def test_corrupt_feed_and_invalid_credentials_do_not_reach_server(self):
        self.publish(False, secret='header\ninjection')
        (self.feed / self.name).write_bytes(b'corrupt')
        self.publish(False)
        self.assertEqual(self.requests, [])

    def test_wrong_signature_and_redirect_do_not_publish_or_forward_credentials(self):
        self.publish(False, secret='wrong-secret')
        self.assertEqual(self.requests, [('HEAD', 'latest.yml', False)])
        self.requests.clear()
        self.redirect = True
        self.publish(False)
        self.assertEqual(self.requests, [('HEAD', 'latest.yml', True)])
        self.assertEqual(self.objects, {})

    def test_oversized_object_fails_before_network(self):
        large = Mock(spec=Path)
        large.stat.return_value.st_size = MAX_OBJECT + 1
        publisher = S3Publisher(self.url, 'us-west-2', ACCESS, SECRET, TOKEN, True)
        with self.assertRaisesRegex(ValueError, 'part-count'):
            publisher.publish(self.feed, 'latest.yml', [large])
        self.assertEqual(self.requests, [])

    def multipart_feed(self):
        source = self.root / 'large.exe'
        source.write_bytes(bytes(range(256)) * (2 * MIN_PART // 256) + b'last partial part')
        self.feed = self.root / 'multipart-feed'
        create_feed(artifacts=[{'source': source, 'name': self.name}], package_json=self.root / 'package.json',
                    output=self.feed, platform='windows', architecture='arm64', release_date='2026-01-02T03:04:05Z')
        self.extra_args = ['--multipart-threshold', str(MIN_PART), '--part-size', str(MIN_PART)]

    def test_multipart_exact_parts_conditional_completion_and_identical_retry(self):
        self.multipart_feed()
        self.publish()
        self.assertEqual(self.objects, {path.name: path.read_bytes() for path in self.feed.iterdir()})
        self.assertEqual([method for method, name, _ in self.requests if name == self.name],
                         ['POST', 'PUT', 'PUT', 'PUT', 'POST'])
        self.assertEqual(self.uploads, {})
        self.assertEqual(self.aborted, [])
        self.requests.clear()
        self.publish()
        self.assertEqual(len(self.aborted), 1)
        self.assertEqual(self.uploads, {})
        self.assertTrue(all(valid for _, _, valid in self.requests))
        self.assertIn(('GET', self.name, True), self.requests)

    def test_multipart_failures_abort_owned_upload_without_channel_promotion(self):
        self.multipart_feed()
        for mode in ('part_failure', 'embedded_error', 'completion_conflict'):
            with self.subTest(mode=mode):
                self.multipart_mode = mode
                self.publish(False)
                self.assertEqual(self.objects, {})
                self.assertEqual(self.uploads, {})
        self.assertEqual(len(self.aborted), 3)
        self.multipart_mode = None
        self.publish()

    def test_aws_documented_get_and_put_signature_vectors(self):
        cases = [
            ('GET', '/?lifecycle', {}, b'',
             'fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543'),
            ('GET', '/test.txt', {'Range': 'bytes=0-9'}, b'',
             'f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41'),
            ('PUT', '/test%24file.text', {'Date': 'Fri, 24 May 2013 00:00:00 GMT',
                                        'x-amz-storage-class': 'REDUCED_REDUNDANCY'}, b'Welcome to Amazon S3.',
             '98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd'),
        ]
        for method, path, headers, body, expected in cases:
            with self.subTest(method=method):
                result = signed_headers(method, 'https://examplebucket.s3.amazonaws.com' + path, headers,
                                        hashlib.sha256(body).hexdigest(), 'AKIAIOSFODNN7EXAMPLE',
                                        'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY', 'us-east-1', '20130524T000000Z')
                self.assertEqual(result['authorization'].split('Signature=')[1], expected)


if __name__ == '__main__':
    unittest.main()
