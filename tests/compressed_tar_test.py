"""Independent lzip decoding and declared 7zip interoperability on BB."""

import io
import lzma
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zlib
from zipfile import ZipFile, ZipInfo

from electron.private.archive import create_archive

LZIP, SEVENZIP, RULE_LZIP, RULE_SEVENZIP = [str(Path(value).resolve()) for value in sys.argv[1:]]
del sys.argv[1:]


class CompressedTarTest(unittest.TestCase):
    def decode(self, path, format):
        if format == 'tar.7z':
            return subprocess.run([SEVENZIP, 'e', '-so', str(path)], capture_output=True, check=True,
                                  env={'PATH': '', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC'}).stdout
        data = path.read_bytes()
        self.assertEqual(data[:5], b'LZIP\x01')
        code = data[5]
        size = 1 << (code & 31)
        size -= size // 16 * (code >> 5)
        payload = lzma.decompress(data[6:-20], format=lzma.FORMAT_RAW, filters=[
            {'id': lzma.FILTER_LZMA1, 'dict_size': size, 'lc': 3, 'lp': 0, 'pb': 2},
        ])
        self.assertEqual(struct.unpack('<IQQ', data[-20:]), (zlib.crc32(payload), len(payload), len(data)))
        return payload

    def options(self, format):
        return {'lzip': LZIP} if format == 'tar.lz' else {'sevenzip': SEVENZIP}

    def test_tree_links_modes_unicode_and_relocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'first app'
            (app / 'data/empty').mkdir(parents=True)
            (app / 'program').write_bytes(b'executable\0payload')
            (app / 'program').chmod(0o755)
            (app / 'data/世界').write_bytes(b'resource\0' * 8192)
            (app / 'alias').symlink_to('data', target_is_directory=True)
            (app / 'program-link').symlink_to('program')
            mirror = root / 'relocated app'
            shutil.copytree(app, mirror, symlinks=True)
            for path in mirror.rglob('*'):
                os.utime(path, (123456789, 123456789), follow_symlinks=False)
            for format in ('tar.lz', 'tar.7z'):
                for level in (0, 6, 9):
                    with self.subTest(format=format, level=level):
                        first, second = root / ('first.' + format), root / ('other.' + format)
                        create_archive(app, 'linux', 'Sample 世界', format, level, first, **self.options(format))
                        create_archive(mirror, 'linux', 'Sample 世界', format, level, second, **self.options(format))
                        self.assertEqual(first.read_bytes(), second.read_bytes())
                        with tarfile.open(fileobj=io.BytesIO(self.decode(first, format))) as archive:
                            self.assertEqual(archive.extractfile('Sample 世界/program').read(), b'executable\0payload')
                            self.assertEqual(archive.getmember('Sample 世界/program').mode, 0o755)
                            self.assertEqual(archive.extractfile('Sample 世界/data/世界').read(), b'resource\0' * 8192)
                            self.assertEqual(archive.getmember('Sample 世界/alias').linkname, 'data')
                            self.assertEqual(archive.getmember('Sample 世界/program-link').linkname, 'program')
                            self.assertTrue(archive.getmember('Sample 世界/data/empty').isdir())
                            self.assertTrue(all((entry.uid, entry.gid, entry.mtime, entry.uname, entry.gname)
                                                == (0, 0, 0, '', '') for entry in archive))
            self.assertEqual((app / 'program').read_bytes(), b'executable\0payload')
            self.assertEqual((app / 'program').stat().st_mode & 0o777, 0o755)

    def test_signed_mac_zip_preserves_seal_and_framework_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'app.zip'
            with ZipFile(source, 'w') as archive:
                for name, mode, content in [
                    ('Original.app/Contents/MacOS/app', 0o100755, b'signed Mach-O'),
                    ('Original.app/Contents/_CodeSignature/CodeResources', 0o100644, b'signature seal'),
                    ('Original.app/Contents/Frameworks/F.framework/Versions/A/F', 0o100755, b'framework'),
                    ('Original.app/Contents/Frameworks/F.framework/Versions/Current', 0o120777, b'A'),
                    ('Original.app/Contents/Frameworks/F.framework/F', 0o120777, b'Versions/Current/F'),
                ]:
                    entry = ZipInfo(name)
                    entry.create_system, entry.external_attr = 3, mode << 16
                    archive.writestr(entry, content)
            original = source.read_bytes()
            for format in ('tar.lz', 'tar.7z'):
                output = root / ('release.' + format)
                create_archive(source, 'macos', 'Sample.app', format, 1, output, **self.options(format))
                with tarfile.open(fileobj=io.BytesIO(self.decode(output, format))) as archive:
                    self.assertEqual(archive.extractfile('Sample.app/Contents/_CodeSignature/CodeResources').read(), b'signature seal')
                    self.assertEqual(archive.getmember('Sample.app/Contents/Frameworks/F.framework/F').linkname, 'Versions/Current/F')
            self.assertEqual(source.read_bytes(), original)

    def test_missing_tools_and_failed_compression_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'app'
            app.mkdir()
            output = root / 'release'
            for format in ('tar.lz', 'tar.7z'):
                output.write_bytes(b'previous output')
                with self.subTest(format=format), self.assertRaisesRegex(ValueError, 'declared execution tool'):
                    create_archive(app, 'linux', 'Sample', format, 1, output)
                options = {'lzip': str(root / 'missing')} if format == 'tar.lz' else {'sevenzip': str(root / 'missing')}
                with self.assertRaises(FileNotFoundError):
                    create_archive(app, 'linux', 'Sample', format, 1, output, **options)
                self.assertEqual(output.read_bytes(), b'previous output')

    def test_public_rules_contain_real_app_bytes(self):
        for name, format in [(RULE_LZIP, 'tar.lz'), (RULE_SEVENZIP, 'tar.7z')]:
            with self.subTest(format=format), tarfile.open(fileobj=io.BytesIO(self.decode(Path(name), format))) as archive:
                self.assertEqual(archive.extractfile('electron/electron').read()[:4], b'\x7fELF')
                self.assertTrue(archive.getmember('electron/electron').mode & 0o111)
                self.assertEqual(archive.extractfile('electron/icudtl.dat').read(), b'Packaging fixture data; not real ICU data.\n')


if __name__ == '__main__':
    unittest.main()
