import json
import os
import struct
from pathlib import Path
import tarfile
import tempfile
import unittest
import zlib
import xml.etree.ElementTree as ET

from electron.private.linux import create_payload
from electron.private.archive import create_archive


class LinuxPackageTest(unittest.TestCase):
    def png(self, width=2, height=2):
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress((b"\0" + b"\x21\x42\x63\xff" * width) * height)) + chunk(b"IEND", b""))

    def test_file_type_png_and_svg_icons_use_mime_names_and_keep_source_bytes(self):
        png = self.root / "document.png"
        png.write_bytes(self.png())
        sources = [{"source": str(png), "mime_type": "application/x-sample"},
                   {"source": str(self.icon), "mime_type": "application/x-sample"}]
        output = self.payload(file_association_icons=sources)
        with tarfile.open(output) as archive:
            for size, extension, source in [("2x2", ".png", png), ("scalable", ".svg", self.icon)]:
                icon = archive.getmember("usr/share/icons/hicolor/" + size + "/mimetypes/application-x-sample" + extension)
                self.assertEqual(icon.mode, 0o644)
                self.assertEqual(archive.extractfile(icon).read(), source.read_bytes())
        self.assertEqual(png.read_bytes(), self.png())

    def test_file_type_icons_reject_unregistered_duplicate_non_square_and_corrupt_images(self):
        png, other = self.root / "document.png", self.root / "other.png"
        png.write_bytes(self.png())
        other.write_bytes(self.png())
        icons = [{"source": str(png), "mime_type": "application/x-sample"}]
        bad = [([{**icons[0], "mime_type": "application/x-unregistered"}], self.png()),
               (icons + [{"source": str(other), "mime_type": "application/x-sample"}], self.png()),
               (icons, self.png(2, 3)), (icons, self.png()[:-1] + bytes([self.png()[-1] ^ 1])),
               (icons, self.png()[:-5]), (icons, b"not PNG")]
        for index, (mappings, data) in enumerate(bad):
            png.write_bytes(data)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.payload(name="invalid-icon", file_association_icons=mappings)
        self.icon.write_text("<invalid/>")
        with self.assertRaises(ValueError):
            self.payload(name="invalid-icon", file_association_icons=[{"source": str(self.icon), "mime_type": "application/x-sample"}])
        self.assertFalse((self.root / "invalid-icon.tar.gz").exists())

    def test_zip_payload_preserves_directory_aliases_and_matches_directory_bytes(self):
        (self.app / "data/v1").mkdir(parents=True)
        (self.app / "data/v1/payload").write_bytes(b"payload")
        (self.app / "current").symlink_to("data/v1", target_is_directory=True)
        packed = self.root / "input.zip"
        create_archive(self.app, "linux", "App 世界", "zip", 0, packed)
        before = packed.read_bytes()
        tree_payload = self.payload(name="tree")
        zip_payload = self.payload(name="zip", app=packed)
        self.assertEqual(zip_payload.read_bytes(), tree_payload.read_bytes())
        self.assertEqual(packed.read_bytes(), before)
        with tarfile.open(zip_payload) as archive:
            entry = archive.getmember("opt/org.example.sample/current")
            self.assertTrue(entry.issym())
            self.assertEqual(entry.linkname, "data/v1")
            destination = self.root / "installed"
            archive.extractall(destination, filter="data")
        self.assertEqual((destination / "opt/org.example.sample/current/payload").read_bytes(), b"payload")

    def test_setuid_sandbox_sets_only_helper_mode_without_changing_inputs(self):
        helper = self.app / "chrome-sandbox"
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<HH", header, 16, 3, 183)
        helper.write_bytes(header)
        helper.chmod(0o755)
        for enabled, expected_mode in ((False, 0o755), (True, 0o4755)):
            payload = self.payload(name=str(enabled), setuid_sandbox=enabled)
            with tarfile.open(payload) as archive:
                sandbox = archive.getmember("opt/org.example.sample/chrome-sandbox")
                main = archive.getmember("opt/org.example.sample/sample")
                self.assertEqual((sandbox.uid, sandbox.gid, sandbox.mode), (0, 0, expected_mode))
                self.assertEqual(main.mode, 0o755)
                self.assertEqual(archive.extractfile(sandbox).read(), bytes(header))
        self.assertEqual(helper.stat().st_mode & 0o7777, 0o755)

    def test_setuid_sandbox_rejects_missing_linked_wrong_architecture_and_script_helpers(self):
        helper = self.app / "chrome-sandbox"
        with self.assertRaises(ValueError):
            self.payload(name="missing", setuid_sandbox=True)
        helper.symlink_to("sample")
        with self.assertRaises(ValueError):
            self.payload(name="linked", setuid_sandbox=True)
        helper.unlink()
        for header in (b"#!/bin/sh\nexit 0\n", b"\x7fELF\x02\x01" + bytes(10) + struct.pack("<HH", 3, 62)):
            helper.write_bytes(header)
            helper.chmod(0o755)
            with self.subTest(header=header[:6]), self.assertRaises(ValueError):
                self.payload(name="invalid", setuid_sandbox=True)
        for name in ("missing", "linked", "invalid"):
            self.assertFalse((self.root / (name + ".tar.gz")).exists())

    def test_tracked_empty_directories_reach_payload_and_reject_collisions(self):
        manifest = self.root / "directories.json"
        manifest.write_text(json.dumps(["cache/empty", ".hidden"]))
        output = self.payload(directory_manifest=str(manifest))
        with tarfile.open(output) as archive:
            for name in ("cache/empty", ".hidden"):
                entry = archive.getmember("opt/org.example.sample/" + name)
                self.assertTrue(entry.isdir())
                self.assertEqual((entry.mode, entry.mtime), (0o755, 0))
        for paths in (["../escape"], ["sample/child"], ["resource"]):
            manifest.write_text(json.dumps(paths))
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.payload(name="invalid-directories", directory_manifest=str(manifest))
        self.assertFalse((self.root / "invalid-directories.tar.gz").exists())

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.app = self.root / "app"
        self.app.mkdir()
        executable = self.app / "sample"
        executable.write_bytes(b"target executable")
        executable.chmod(0o755)
        (self.app / "resource").write_bytes(b"binary\x00resource")
        (self.app / "resource-link").symlink_to("resource")
        self.package = self.root / "package.json"
        self.package.write_text(json.dumps({"name": "sample", "version": "1.2.3-beta.2+build.7"}))
        self.icon = self.root / "sample.svg"
        self.icon.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

    def payload(self, name="payload", **kwargs):
        options = dict(
            app=self.app, package_json=self.package, app_id="org.example.sample",
            product_name="Sample 世界\nInjected=false", executable_name="sample",
            architecture="arm64", revision="2", description="A sample app",
            categories=["Utility"], protocols=["sample+test"],
            file_associations={"application/x-sample": ["*.sample", "*.test&sample"]},
            icons=[{"source": str(self.icon), "size": "scalable"}],
            output=self.root / (name + ".tar.gz"), version_output=self.root / (name + ".version"),
        )
        options.update(kwargs)
        create_payload(**options)
        return self.root / (name + ".tar.gz")

    def test_payload_metadata_modes_symlinks_and_reproducibility(self):
        first = self.payload()
        os.utime(self.app / "sample", (123456789, 123456789))
        second = self.payload("repeat")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual((self.root / "payload.version").read_text(), "1.2.3~beta.2+build.7-2\n")
        with tarfile.open(first) as archive:
            executable = archive.getmember("opt/org.example.sample/sample")
            self.assertEqual(executable.mode, 0o755)
            resource = archive.getmember("opt/org.example.sample/resource")
            self.assertEqual(resource.mode, 0o644)
            self.assertEqual(archive.extractfile(resource).read(), b"binary\x00resource")
            self.assertEqual(archive.getmember("opt/org.example.sample/resource-link").linkname, "resource")
            launcher = archive.extractfile("usr/bin/sample").read().decode()
            self.assertIn('exec /opt/org.example.sample/sample "$@"', launcher)
            desktop = archive.extractfile("usr/share/applications/org.example.sample.desktop").read().decode()
            self.assertIn("Name=Sample 世界\\nInjected=false\n", desktop)
            self.assertNotIn("\nInjected=", desktop)
            self.assertIn("Exec=/opt/org.example.sample/sample %U\n", desktop)
            self.assertIn("MimeType=x-scheme-handler/sample+test;application/x-sample;\n", desktop)
            metadata = ET.fromstring(archive.extractfile("usr/share/mime/packages/org.example.sample.xml").read())
            namespace = {"m": "http://www.freedesktop.org/standards/shared-mime-info"}
            self.assertEqual([n.attrib["pattern"] for n in metadata.findall("m:mime-type/m:glob", namespace)], ["*.sample", "*.test&sample"])
            self.assertEqual(archive.extractfile("opt/org.example.sample/resources/package-type").read(), b"deb\n")
            self.assertEqual(archive.extractfile("usr/share/icons/hicolor/scalable/apps/org.example.sample.svg").read(), self.icon.read_bytes())
            for member in archive:
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))

    def test_invalid_metadata_and_conflicting_package_type_fail(self):
        for kwargs in [
            {"app_id": "../escape"}, {"executable_name": "sample --flag"},
            {"protocols": ["bad;scheme"]}, {"categories": ["Utility\nType=Link"]},
            {"file_associations": {"invalid": ["*.x"]}},
            {"file_associations": {"application/x-sample": ["../*.x"]}},
            {"revision": "1\nPackage: injection"}, {"architecture": "host"},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.payload(**kwargs)
        resources = self.app / "resources"
        resources.mkdir()
        (resources / "package-type").write_text("rpm\n")
        with self.assertRaisesRegex(ValueError, "conflicting package-type"):
            self.payload()

    def test_escaping_and_absolute_symlinks_fail(self):
        link = self.app / "bad"
        for target in ["../package.json", str(self.app / "resource")]:
            link.symlink_to(target)
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.payload()
            link.unlink()


if __name__ == "__main__":
    unittest.main()
