"""Bind update descriptors to immutable MSIX identity and explicit policy."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from electron.private.appinstaller import BUNDLE, BUNDLE_MANIFEST, FOUNDATION, NAMESPACE, create_appinstaller


class AppInstallerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / 'signed.msix'
        self.output = self.root / 'release.appinstaller'
        self.manifest = ('<Package xmlns="' + FOUNDATION + '"><Identity Name="org.example.Sample" '
                         'Publisher="CN=Example &amp; Sons" Version="2.3.4.7" ProcessorArchitecture="arm64"/></Package>')
        self.write_manifest(self.manifest.encode())

    def write_manifest(self, data):
        with ZipFile(self.package, 'w') as archive:
            archive.writestr('AppxManifest.xml', data)

    def render(self, package_uri='https://updates.example.invalid/Sample%20Setup.msix', **options):
        create_appinstaller(package=self.package, output=self.output,
                            appinstaller_uri='https://updates.example.invalid/latest.appinstaller',
                            package_uri=package_uri, **options)
        return ET.fromstring(self.output.read_bytes())

    def test_identity_and_policy_come_from_declared_bytes_and_options(self):
        before = hashlib.sha256(self.package.read_bytes()).digest()
        root = self.render(appinstaller_version='3.0.0.0', hours_between_update_checks=0,
                           show_prompt=True, update_blocks_activation=True, automatic_background_task=True,
                           force_update_from_any_version=True,
                           update_uris=['https://fallback.example.invalid/latest.appinstaller'])
        ns = '{' + NAMESPACE + '}'
        self.assertEqual(root.tag, ns + 'AppInstaller')
        self.assertEqual(root.attrib['Version'], '3.0.0.0')
        self.assertEqual(root.find(ns + 'MainPackage').attrib, {
            'Name': 'org.example.Sample', 'Publisher': 'CN=Example & Sons', 'Version': '2.3.4.7',
            'ProcessorArchitecture': 'arm64', 'Uri': 'https://updates.example.invalid/Sample%20Setup.msix',
        })
        settings = root.find(ns + 'UpdateSettings')
        self.assertEqual(settings.find(ns + 'OnLaunch').attrib,
                         {'HoursBetweenUpdateChecks': '0', 'ShowPrompt': 'true', 'UpdateBlocksActivation': 'true'})
        self.assertIsNotNone(settings.find(ns + 'AutomaticBackgroundTask'))
        self.assertEqual(settings.find(ns + 'ForceUpdateFromAnyVersion').text, 'true')
        self.assertEqual(root.find(ns + 'UpdateUris')[0].text, 'https://fallback.example.invalid/latest.appinstaller')
        self.assertEqual(hashlib.sha256(self.package.read_bytes()).digest(), before)

    def test_relocation_mtime_and_manifest_encoding_preserve_output(self):
        self.render()
        expected = self.output.read_bytes()
        destination = self.root / 'relocated' / 'different.msix'
        destination.parent.mkdir()
        shutil.copyfile(self.package, destination)
        os.utime(destination, (123456789, 123456789))
        self.package = destination
        self.render()
        self.assertEqual(self.output.read_bytes(), expected)
        self.write_manifest(self.manifest.encode('utf-16'))
        self.render()
        self.assertEqual(self.output.read_bytes(), expected)

    def test_bundle_uses_bundle_identity_without_cpu_and_preserves_bytes(self):
        self.package = self.root / 'signed.msixbundle'
        with ZipFile(self.package, 'w') as archive:
            archive.writestr(BUNDLE_MANIFEST, '<Bundle xmlns="' + BUNDLE + '"><Identity '
                             'Name="org.example.Bundle" Publisher="CN=Example" Version="4.5.6.7"/></Bundle>')
            archive.writestr('package-arm64.msix', b'unchanged inner package')
        before = self.package.read_bytes()
        root = self.render(package_uri='https://updates.example.invalid/Sample.msixbundle')
        ns = '{' + NAMESPACE + '}'
        self.assertIsNone(root.find(ns + 'MainPackage'))
        self.assertEqual(root.find(ns + 'MainBundle').attrib, {
            'Name': 'org.example.Bundle', 'Publisher': 'CN=Example', 'Version': '4.5.6.7',
            'Uri': 'https://updates.example.invalid/Sample.msixbundle',
        })
        self.assertEqual(root.attrib['Version'], '4.5.6.7')
        self.assertEqual(self.package.read_bytes(), before)
        with ZipFile(self.package, 'a') as archive:
            archive.writestr('AppxManifest.xml', self.manifest)
        with self.assertRaisesRegex(ValueError, 'both package and bundle'):
            self.render()

    def test_invalid_versions_policies_and_fallbacks_fail(self):
        for options in ({'appinstaller_version': '1.2.3'}, {'appinstaller_version': '1.2.3.65536'},
                        {'hours_between_update_checks': 256}, {'hours_between_update_checks': True},
                        {'update_blocks_activation': True}, {'check_on_launch': False, 'show_prompt': True},
                        {'update_uris': ['https://example.invalid/a'] * 2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.render(**options)

    def test_unsafe_urls_and_external_entities_fail(self):
        for address in ('http://example.invalid/a', 'https://user:secret@example.invalid/a',
                        'https://example.invalid/a?token=value', 'https://example.invalid/世界.msix'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                create_appinstaller(self.package, self.output, address, address)
        self.write_manifest(b'<!DOCTYPE Package [<!ENTITY name "org.example.Sample">]>' + self.manifest.encode())
        with self.assertRaisesRegex(ValueError, 'document type'):
            self.render()

    def test_loopback_is_explicit_and_missing_identity_fails(self):
        for allowed in (False, True):
            if allowed:
                create_appinstaller(self.package, self.output, 'http://127.0.0.1:1234/latest.appinstaller',
                                    'http://127.0.0.1:1234/app.msix', allow_http_loopback=True)
            else:
                with self.assertRaises(ValueError):
                    create_appinstaller(self.package, self.output, 'http://127.0.0.1/latest.appinstaller',
                                        'http://127.0.0.1/app.msix')
        self.write_manifest(('<Package xmlns="' + FOUNDATION + '"/>').encode())
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.render()


if __name__ == '__main__':
    unittest.main()
