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
from urllib.parse import unquote

from electron.private.update import create_feed
from electron.tools.publish_s3 import S3Publisher, signed_headers

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
    required = {'host', 'x-amz-date', 'x-amz-content-sha256', 'x-amz-security-token'}
    if request.command == 'PUT':
        required.update({'content-length', 'content-type'})
        required.add('if-match' if request.headers.get('If-Match') else 'if-none-match')
    if names != sorted(set(names)) or not required.issubset(names):
        return False
    timestamp = request.headers['x-amz-date']
    if (timestamp[:8] != date or request.headers['x-amz-security-token'] != TOKEN
            or request.headers['x-amz-content-sha256'] != hashlib.sha256(body).hexdigest()
            or abs((datetime.now(timezone.utc) - datetime.strptime(timestamp, '%Y%m%dT%H%M%SZ')
                    .replace(tzinfo=timezone.utc)).total_seconds()) > 120):
        return False
    canonical = request.command + '\n' + request.path + '\n\n'
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
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                name = unquote(self.path[len(PREFIX):])
                valid = authorized(self, body) and self.path.startswith(PREFIX)
                owner.requests.append((self.command, name, valid))
                status, reply = 200, b''
                if not valid:
                    status = 403
                elif owner.redirect:
                    status = 307
                elif self.command == 'HEAD':
                    status = 200 if name in owner.objects else 404
                elif self.command == 'GET':
                    status = 200 if name in owner.objects else 404
                    reply = owner.objects.get(name, b'')
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
                if owner.redirect:
                    self.send_header('Location', owner.url + 'credential-target')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(reply)

            do_HEAD = do_GET = do_PUT = handle_request

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
        ], env={**os.environ, 'FIXTURE_ACCESS': ACCESS, 'FIXTURE_SECRET': secret, 'FIXTURE_TOKEN': TOKEN},
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

    def test_oversized_single_part_fails_before_network(self):
        large = self.root / 'large.exe'
        with large.open('wb') as output:
            output.truncate(5 * 1024**3 + 1)
        publisher = S3Publisher(self.url, 'us-west-2', ACCESS, SECRET, TOKEN, True)
        with self.assertRaisesRegex(ValueError, 'single-part'):
            publisher.publish(self.feed, 'latest.yml', [large])
        self.assertEqual(self.requests, [])

    def test_aws_documented_get_and_put_signature_vectors(self):
        cases = [
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
