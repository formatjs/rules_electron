"""Verify immutable MSIX publication, identity binding, MIME and promotion races."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import quote, unquote
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from electron.private.appinstaller import FOUNDATION, NAMESPACE, create_appinstaller
from tests.s3_test_support import ACCESS, PREFIX, SECRET, TOKEN, authorized

TOOL = Path(sys.argv.pop(1)).resolve()


class AppInstallerPublicationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / 'build-output.msix'
        self.name = 'Example 世界.msix'
        with ZipFile(self.package, 'w') as archive:
            archive.writestr('AppxManifest.xml', '<Package xmlns="' + FOUNDATION + '"><Identity '
                             'Name="org.example.Sample" Publisher="CN=Example" Version="2.0.0.7" '
                             'ProcessorArchitecture="arm64"/></Package>')
            archive.writestr('payload.bin', bytes(range(256)) * 1024)
        self.descriptor = self.root / 'build-output.appinstaller'
        create_appinstaller(self.package, self.descriptor, 'https://updates.example.invalid/latest.appinstaller',
                            'https://updates.example.invalid/' + quote(self.name))
        self.objects, self.requests, self.race = {}, [], False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                name = unquote(self.path[len(PREFIX):])
                valid = authorized(self, body) and self.path.startswith(PREFIX)
                owner.requests.append((self.command, name, self.headers.get('Content-Type'), valid))
                status, reply = 200, b''
                if not valid:
                    status = 403
                elif self.command == 'HEAD':
                    status = 200 if name in owner.objects else 404
                elif self.command == 'GET':
                    status = 200 if name in owner.objects else 404
                    reply = owner.objects.get(name, b'')
                elif name == 'latest.appinstaller' and owner.race:
                    owner.objects[name] = b'concurrent descriptor'
                    status = 412
                elif ((self.headers.get('If-None-Match') == '*' and name in owner.objects)
                      or (name in owner.objects and self.headers.get('If-Match') != '"fixture-etag"')):
                    status = 412
                else:
                    owner.objects[name] = body
                self.send_response(status)
                self.send_header('Content-Length', str(len(reply)))
                if name == 'latest.appinstaller' and status == 200:
                    self.send_header('ETag', '"fixture-etag"')
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

    def publish(self, success=True):
        result = subprocess.run([
            str(TOOL), '--descriptor', str(self.descriptor), '--package', str(self.package),
            '--destination', self.url, '--region', 'us-west-2', '--allow-http-loopback',
            '--access-key-env', 'FIXTURE_ACCESS', '--secret-key-env', 'FIXTURE_SECRET',
            '--session-token-env', 'FIXTURE_TOKEN',
        ], env={**os.environ, 'FIXTURE_ACCESS': ACCESS, 'FIXTURE_SECRET': SECRET, 'FIXTURE_TOKEN': TOKEN},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        for value in (ACCESS, SECRET, TOKEN):
            self.assertNotIn(value.encode(), result.stdout + result.stderr)
        self.assertEqual(result.stdout if success else result.stderr,
                         b'APPINSTALLER_PUBLISHED\n' if success else b'APPINSTALLER_PUBLICATION_FAILED\n')

    def test_exact_bytes_names_mime_order_and_retry(self):
        expected = {self.name: self.package.read_bytes(), 'latest.appinstaller': self.descriptor.read_bytes()}
        self.publish()
        self.assertEqual(self.objects, expected)
        self.assertEqual(self.requests, [
            ('HEAD', 'latest.appinstaller', None, True),
            ('PUT', self.name, 'application/msix', True),
            ('PUT', 'latest.appinstaller', 'application/appinstaller', True),
        ])
        self.requests.clear()
        self.publish()
        self.assertEqual(self.objects, expected)
        self.assertIn(('GET', self.name, None, True), self.requests)
        self.assertEqual(self.package.read_bytes(), expected[self.name])
        self.assertEqual(self.descriptor.read_bytes(), expected['latest.appinstaller'])

    def test_identity_extra_packages_and_unsafe_urls_fail_before_network(self):
        original = self.descriptor.read_bytes()
        ns = '{' + NAMESPACE + '}'
        for change in ('identity', 'extra', 'url', 'slash', 'fallback'):
            root = ET.fromstring(original)
            if change == 'identity':
                root.find(ns + 'MainPackage').set('Version', '9.0.0.0')
            elif change == 'extra':
                ET.SubElement(root, ns + 'Dependencies')
            elif change == 'url':
                root.set('Uri', 'https://user:secret@example.invalid/latest.appinstaller')
            elif change == 'slash':
                main = root.find(ns + 'MainPackage')
                main.set('Uri', main.attrib['Uri'] + '/')
            else:
                ET.SubElement(ET.SubElement(root, ns + 'UpdateUris'), ns + 'UpdateUri').text = 'https://user:secret@example.invalid/fallback.appinstaller'
            self.descriptor.write_bytes(ET.tostring(root))
            self.publish(False)
        self.assertEqual(self.requests, [])

    def test_conflicting_package_and_channel_race_preserve_descriptor(self):
        self.objects.update({self.name: b'other package', 'latest.appinstaller': b'old descriptor'})
        self.publish(False)
        self.assertEqual(self.objects['latest.appinstaller'], b'old descriptor')
        self.objects[self.name] = self.package.read_bytes()
        self.race = True
        self.publish(False)
        self.assertEqual(self.objects['latest.appinstaller'], b'concurrent descriptor')

    def test_symlink_inputs_fail_before_network(self):
        link = self.root / 'linked.msix'
        link.symlink_to(self.package)
        self.package = link
        self.publish(False)
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()
