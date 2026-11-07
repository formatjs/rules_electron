import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tarfile
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from electron.private.archive import create_archive


RULE_OUTPUTS = sys.argv[1:]
del sys.argv[1:]


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.app = self.root / "first app"
        self.app.mkdir()
        (self.app / "sample").write_bytes(b"executable\0bytes")
        (self.app / "sample").chmod(0o755)
        (self.app / "resource 世界").write_bytes(b"resource\0bytes")
        (self.app / "resource 世界").chmod(0o644)
        (self.app / "empty").mkdir()
        (self.app / "link").symlink_to("resource 世界")

    def archive(self, format="zip", source=None, platform="linux", root_name="Sample 世界", level=6, name="release"):
        output = self.root / (name + "." + format)
        create_archive(source or self.app, platform, root_name, format, level, output)
        return output

    def test_tree_modes_bytes_links_and_reproducibility(self):
        for format in ("zip", "tar.gz"):
            for level in (0, 9):
                with self.subTest(format=format, level=level):
                    first = self.archive(format, level=level)
                    relocated = self.root / f"other-{format}-{level}"
                    shutil.copytree(self.app, relocated, symlinks=True)
                    for path in relocated.rglob("*"):
                        os.utime(path, (1234567890, 1234567890), follow_symlinks=False)
                    second = self.archive(format, source=relocated, level=level, name="other")
                    self.assertEqual(first.read_bytes(), second.read_bytes())
                    if format == "zip":
                        with ZipFile(first) as archive:
                            self.assertEqual(archive.read("Sample 世界/sample"), b"executable\0bytes")
                            self.assertEqual(archive.read("Sample 世界/link").decode(), "resource 世界")
                            self.assertEqual(archive.getinfo("Sample 世界/sample").external_attr >> 16, stat.S_IFREG | 0o755)
                            self.assertEqual(archive.getinfo("Sample 世界/resource 世界").external_attr >> 16, stat.S_IFREG | 0o644)
                            self.assertTrue(stat.S_ISLNK(archive.getinfo("Sample 世界/link").external_attr >> 16))
                            self.assertTrue(archive.getinfo("Sample 世界/empty/").is_dir())
                            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))
                            if level == 0:
                                self.assertTrue(all(info.compress_type == ZIP_STORED for info in archive.infolist()))
                    else:
                        with tarfile.open(first) as archive:
                            self.assertEqual(archive.extractfile("Sample 世界/sample").read(), b"executable\0bytes")
                            self.assertEqual(archive.getmember("Sample 世界/sample").mode, 0o755)
                            self.assertEqual(archive.getmember("Sample 世界/resource 世界").mode, 0o644)
                            self.assertEqual(archive.getmember("Sample 世界/link").linkname, "resource 世界")
                            self.assertTrue(archive.getmember("Sample 世界/empty").isdir())
                            self.assertTrue(all((entry.uid, entry.gid, entry.mtime, entry.uname, entry.gname) == (0, 0, 0, "", "") for entry in archive))

    def mac_input(self, entries, name="input"):
        output = self.root / (name + ".zip")
        with ZipFile(output, "w") as archive:
            for path, mode, content in entries:
                info = ZipInfo(path)
                info.create_system = 3
                info.external_attr = mode << 16
                archive.writestr(info, content)
        return output

    def test_macos_zip_preserves_signed_bytes_and_framework_links(self):
        entries = [
            ("Old.app/Contents/MacOS/sample", stat.S_IFREG | 0o755, b"Mach-O with signature bytes\0"),
            ("Old.app/Contents/_CodeSignature/CodeResources", stat.S_IFREG | 0o644, b"signed resource manifest"),
            ("Old.app/Contents/Frameworks/F.framework/Versions/A/F", stat.S_IFREG | 0o755, b"framework"),
            ("Old.app/Contents/Frameworks/F.framework/Versions/Current", stat.S_IFLNK | 0o777, b"A"),
            ("Old.app/Contents/Frameworks/F.framework/F", stat.S_IFLNK | 0o777, b"Versions/Current/F"),
        ]
        source = self.mac_input(entries)
        reverse = self.mac_input(list(reversed(entries)), name="reordered")
        for format in ("zip", "tar.gz"):
            output = self.archive(format, source=source, platform="macos", root_name="Sample.app")
            repeat = self.archive(format, source=reverse, platform="macos", root_name="Sample.app", name="repeat")
            self.assertEqual(output.read_bytes(), repeat.read_bytes())
            if format == "zip":
                with ZipFile(output) as archive:
                    for path, mode, content in entries:
                        name = path.replace("Old.app/", "Sample.app/", 1)
                        self.assertEqual(archive.read(name), content)
                        self.assertEqual(archive.getinfo(name).external_attr >> 16, mode)
            else:
                with tarfile.open(output) as archive:
                    self.assertEqual(archive.getmember("Sample.app/Contents/Frameworks/F.framework/F").linkname, "Versions/Current/F")
                    self.assertEqual(archive.extractfile("Sample.app/Contents/_CodeSignature/CodeResources").read(), b"signed resource manifest")

    def test_invalid_archive_graphs_fail(self):
        for target in ("/outside", "../outside", "missing", "link", "C:/outside", "empty/../../outside", "sample/../resource 世界"):
            (self.app / "link").unlink()
            (self.app / "link").symlink_to(target)
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.archive()
        bad_inputs = [
            [("Old.app/../escape", stat.S_IFREG, b"x")],
            [("Old.app/file", stat.S_IFREG, b"x"), ("Old.app/file", stat.S_IFREG, b"y")],
            [("Old.app/file", stat.S_IFREG, b"x"), ("Old.app/file/child", stat.S_IFREG, b"y")],
            [("Old.app/a", stat.S_IFREG, b"x"), ("Other.app/b", stat.S_IFREG, b"y")],
            [("Old.app/a", stat.S_IFREG, b"x"), ("Old.app/A", stat.S_IFREG, b"y")],
            [("Old.app/device", stat.S_IFCHR, b"")],
        ]
        for entries in bad_inputs:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.archive(source=self.mac_input(entries), platform="macos", root_name="Sample.app")

    def test_symlink_parent_components_follow_directory_links(self):
        (self.app / "folder/sub").mkdir(parents=True)
        (self.app / "folder/data").write_bytes(b"data")
        (self.app / "alias").symlink_to("folder/sub")
        (self.app / "relative").symlink_to("alias/../data")
        output = self.archive()
        with ZipFile(output) as archive:
            self.assertEqual(archive.read("Sample 世界/relative"), b"alias/../data")

    def test_bazel_rule_outputs_contain_actual_app(self):
        self.assertEqual(len(RULE_OUTPUTS), 2, "Expected ZIP and tar.gz rule outputs")
        with ZipFile(RULE_OUTPUTS[0]) as archive:
            self.assertEqual(archive.read("electron/electron")[:4], b"\x7fELF")
            self.assertTrue(archive.getinfo("electron/electron").external_attr >> 16 & 0o111)
            self.assertEqual(json.loads(archive.read("electron/resources/app/package.json"))["name"], "packaging-fixture")
        with tarfile.open(RULE_OUTPUTS[1]) as archive:
            self.assertEqual(archive.extractfile("electron/electron").read()[:4], b"\x7fELF")
            self.assertEqual(archive.extractfile("electron/icudtl.dat").read(), b"Packaging fixture data; not real ICU data.\n")


if __name__ == "__main__":
    unittest.main()
