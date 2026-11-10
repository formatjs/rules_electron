"""Portable extraction boundaries and reproducible script inputs."""

import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from electron.private.portable import build_portable, portable_script


class PortableTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        (self.app / 'sample.exe').write_bytes(b'payload')
        self.package = self.root / 'package.json'
        self.package.write_text('{"version":"1.2.3"}')

    def render(self, **options):
        return portable_script(self.app, self.package, 'org.example.sample', 'Sample', 'sample',
                               self.root / 'portable.exe', compression='zlib', **options)

    def test_launch_has_owned_cleanup_and_no_installation_side_effects(self):
        script = self.render()
        self.assertIn('StrCpy $INSTDIR "$PLUGINSDIR\\app"', script)
        self.assertIn('RequestExecutionLevel user', script)
        self.assertIn('kernel32::GetCommandLineW()', script)
        self.assertNotIn('$CMDLINE', script)
        self.assertLess(script.index('ExecWait'), script.index('RMDir /r "$INSTDIR"'))
        self.assertIn('SetErrorLevel $R2', script)
        for command in ('WriteReg', 'CreateShortcut', 'WriteUninstaller', 'RMDir /r "$EXEDIR"'):
            self.assertNotIn(command, script)
        for name in ('DIR', 'FILE', 'APP_FILENAME'):
            self.assertIn('PORTABLE_EXECUTABLE_' + name, script)

    def test_relocated_inputs_keep_logical_script_and_tracked_empty_directories(self):
        manifest = self.root / 'directories.json'
        manifest.write_text(json.dumps(['resources/cache/empty']))
        mirror = self.root / 'different root' / 'renamed app'
        shutil.copytree(self.app, mirror)

        def render(app):
            def logical(path, role):
                return 'app/' + path.relative_to(app).as_posix() if role == 'app' else 'portable.exe'
            return portable_script(app, self.package, 'org.example.sample', 'Sample', 'sample',
                                   self.root / 'portable.exe', compression='zlib', directory_manifest=manifest,
                                   path_format=logical)

        script = render(self.app)
        self.assertEqual(script, render(mirror))
        self.assertNotIn(str(self.root), script)
        self.assertIn('CreateDirectory "$INSTDIR\\resources\\cache\\empty"', script)

    def test_unsafe_payload_or_environment_name_fails_before_compilation(self):
        for name in ('SAMPLE.exe', 'CON', 'bad${__FILE__}'):
            path = self.app / name
            path.write_bytes(b'bad')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.render()
            path.unlink()
        (self.app / 'link').symlink_to(self.package)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.render()
        (self.app / 'link').unlink()
        for value in ('${HOST}', 'name\nline', '../escape'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.render(app_filename=value)

    def test_payload_architecture_checked_without_invoking_host_compiler(self):
        header = bytearray(70)
        header[:2] = b'MZ'
        struct.pack_into('<I', header, 60, 64)
        header[64:68] = b'PE\0\0'
        struct.pack_into('<H', header, 68, 0x8664)
        (self.app / 'sample.exe').write_bytes(header)
        with self.assertRaisesRegex(ValueError, 'architecture mismatch'):
            build_portable({'app': str(self.app), 'executable_name': 'sample', 'architecture': 'arm64',
                            'compiler': '/not-a-host-tool', 'data': '/not-host-data'},
                           self.root / 'portable.exe', self.root / 'portable.nsi')


if __name__ == '__main__':
    unittest.main()
