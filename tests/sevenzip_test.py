"""Real declared 7zip roundtrips, relocation and immutable-input checks."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from electron.private.archive import create_archive

TOOL = str(Path(sys.argv[1]).resolve())


class SevenzipTest(unittest.TestCase):
    def test_tree_links_empty_directories_unicode_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "app"
            (app / "data/empty").mkdir(parents=True)
            (app / "program").write_bytes(b"executable payload")
            (app / "program").chmod(0o755)
            (app / "data/世界").write_bytes(b"resource")
            (app / "alias").symlink_to("data", target_is_directory=True)
            (app / "program-link").symlink_to("program")
            for level in (0, 1, 9):
                first, second = root / (str(level) + ".7z"), root / (str(level) + "-repeat.7z")
                create_archive(app, "linux", "Sample 世界", "7z", level, first, sevenzip=TOOL)
                mirror = root / ("relocated-" + str(level))
                shutil.copytree(app, mirror, symlinks=True)
                for file in mirror.rglob("*"):
                    if not file.is_symlink():
                        os.utime(file, (123456789, 123456789))
                create_archive(mirror, "linux", "Sample 世界", "7z", level, second, sevenzip=TOOL)
                self.assertEqual(first.read_bytes(), second.read_bytes())
                extracted = root / ("extracted-" + str(level))
                subprocess.run([TOOL, "x", "-y", "-bso0", "-bsp0", "-o" + str(extracted), str(first)],
                               env={"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC"}, check=True)
                app_out = extracted / "Sample 世界"
                self.assertEqual((app_out / "alias/世界").read_bytes(), b"resource")
                self.assertEqual(os.readlink(app_out / "alias"), "data")
                self.assertEqual(os.readlink(app_out / "program-link"), "program")
                self.assertEqual((app_out / "program").stat().st_mode & 0o777, 0o755)
                self.assertTrue((app_out / "data/empty").is_dir())
            self.assertEqual((app / "program").read_bytes(), b"executable payload")
            self.assertEqual((app / "program").stat().st_mode & 0o777, 0o755)

    def test_signed_zip_bytes_and_framework_links_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "app.zip", root / "release.7z"
            with ZipFile(source, "w") as archive:
                for name, mode, data in [
                    ("Original.app/Contents/MacOS/app", 0o100755, b"signed executable"),
                    ("Original.app/Contents/_CodeSignature/CodeResources", 0o100644, b"signature seal"),
                    ("Original.app/Contents/Frameworks/F.framework/Versions/A/F", 0o100755, b"signed framework"),
                    ("Original.app/Contents/Frameworks/F.framework/Versions/Current", 0o120777, b"A"),
                    ("Original.app/Contents/Frameworks/F.framework/F", 0o120777, b"Versions/Current/F"),
                ]:
                    info = ZipInfo(name)
                    info.create_system, info.external_attr = 3, mode << 16
                    archive.writestr(info, data)
            before = source.read_bytes()
            create_archive(source, "macos", "Sample.app", "7z", 1, output, sevenzip=TOOL)
            extracted = root / "extracted"
            subprocess.run([TOOL, "x", "-y", "-bso0", "-bsp0", "-o" + str(extracted), str(output)],
                           env={"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC"}, check=True)
            self.assertEqual((extracted / "Sample.app/Contents/Frameworks/F.framework/F").read_bytes(), b"signed framework")
            self.assertEqual((extracted / "Sample.app/Contents/_CodeSignature/CodeResources").read_bytes(), b"signature seal")
            self.assertEqual(source.read_bytes(), before)

    def test_missing_execution_tool_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app").mkdir()
            with self.assertRaisesRegex(ValueError, "declared execution tool"):
                create_archive(root / "app", "linux", "Sample", "7z", 1, root / "out.7z")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
