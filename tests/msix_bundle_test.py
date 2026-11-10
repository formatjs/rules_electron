"""Independently inspect bundle offsets, block coverage and immutable payloads."""

import base64
import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from urllib.parse import quote
from xml.etree import ElementTree as ET
from zipfile import ZIP_STORED, ZipFile

from electron.private.msix import BLOCK, PackageZip, manifest
from electron.private.msix_bundle import BUNDLE, MANIFEST, create_bundle


class MsixBundleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / 'release.msixbundle'
        self.packages = [self.package(cpu) for cpu in ('arm64', 'x64')]

    def package(self, cpu, version='1.2.3.7', description='Same app'):
        target = self.root / (cpu + '-' + version + '-' + str(len(description))) / 'app.msix'
        target.parent.mkdir(exist_ok=True)
        data = manifest('org.example.Sample', 'CN=Example', 'Example', 'Sample', 'sample.exe',
                        cpu, version, description)
        with target.open('wb') as destination:
            writer = PackageZip(destination)
            writer.add('sample.exe', io.BytesIO(bytes(range(256)) * 400), 'application/octet-stream')
            writer.add('AppxManifest.xml', io.BytesIO(data), 'application/vnd.ms-appx.manifest+xml')
            writer.close()
        return target

    def test_exact_embedded_bytes_offsets_and_single_manifest_blockmap(self):
        names = {cpu: 'Sample ' + cpu + ' 世界.msix' for cpu in ('arm64', 'x64')}
        create_bundle(self.packages, self.output, package_names=names)
        data = self.output.read_bytes()
        with ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            root = ET.fromstring(archive.read(MANIFEST))
            ns = '{' + BUNDLE + '}'
            self.assertEqual(root.tag, ns + 'Bundle')
            self.assertEqual(root.find(ns + 'Identity').attrib,
                             {'Name': 'org.example.Sample', 'Publisher': 'CN=Example', 'Version': '1.2.3.7'})
            entries = root.find(ns + 'Packages')
            self.assertEqual({entry.attrib['Architecture'] for entry in entries}, {'arm64', 'x64'})
            for entry in entries:
                name = entry.attrib['FileName']
                info = archive.getinfo(quote(name, safe='/-._~'))
                fields = struct.unpack_from('<IHHHHHIIIHH', data, info.header_offset)
                start = info.header_offset + 30 + fields[-2] + fields[-1]
                payload = next(path for path in self.packages if path.parent.name.startswith(entry.attrib['Architecture'])).read_bytes()
                self.assertEqual(info.compress_type, ZIP_STORED)
                self.assertEqual(int(entry.attrib['Offset']), start)
                self.assertEqual(int(entry.attrib['Size']), len(payload))
                self.assertEqual(data[start:start + len(payload)], payload)
                self.assertEqual(archive.read(info), payload)
            blockmap = ET.fromstring(archive.read('AppxBlockMap.xml'))
            self.assertEqual([node.attrib['Name'] for node in blockmap], [MANIFEST.replace('/', '\\')])
            expected = archive.read(MANIFEST)
            self.assertEqual([node.attrib['Hash'] for node in blockmap[0]], [
                base64.b64encode(hashlib.sha256(expected[offset:offset + 65536]).digest()).decode()
                for offset in range(0, len(expected), 65536)
            ])
            self.assertEqual(blockmap.tag, '{' + BLOCK + '}BlockMap')

    def test_order_paths_and_mtimes_do_not_change_bundle(self):
        create_bundle(self.packages, self.output)
        expected = self.output.read_bytes()
        relocated = []
        for index, source in enumerate(reversed(self.packages)):
            target = self.root / ('renamed-' + str(index) + '.msix')
            target.write_bytes(source.read_bytes())
            os.utime(target, (123456789, 123456789))
            relocated.append(target)
        create_bundle(relocated, self.output)
        self.assertEqual(self.output.read_bytes(), expected)

    def test_mixed_identity_manifest_or_duplicate_cpu_fails(self):
        bad = [[], [self.packages[0]] * 2,
               [self.packages[0], self.package('x64', version='2.0.0.0')],
               [self.packages[0], self.package('x64', description='Different app')]]
        for packages in bad:
            with self.subTest(packages=packages), self.assertRaises(ValueError):
                create_bundle(packages, self.output)

    def test_unsafe_or_colliding_names_and_unused_mapping_fail(self):
        for names in ({'x64': '../escape.msix'}, {'x64': 'CON.msix'},
                      {'x64': 'SAME.msix', 'arm64': 'same.msix'}, {'x86': 'unused.msix'}):
            with self.subTest(names=names), self.assertRaises(ValueError):
                create_bundle(self.packages, self.output, package_names=names)
        with self.assertRaises(ValueError):
            create_bundle(self.packages, self.output, bundle_version='1.2.3')


if __name__ == '__main__':
    unittest.main()
