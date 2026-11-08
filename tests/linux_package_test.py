import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET

from electron.private.linux import create_payload


class LinuxPackageTest(unittest.TestCase):
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
