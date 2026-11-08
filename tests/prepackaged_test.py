import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct
import tempfile
import unittest

from electron.private.archive import create_archive
from electron.private.asar import create_archive as create_asar
from electron.private.prepackaged import validate


class PrepackagedTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "expected.json"
        self.package.write_text(json.dumps({"name": "sample", "version": "1.2.3", "main": "main.cjs"}))

    def fixture(self, platform="linux", cpu="x86_64", packed=False, unpacked=False, linked=False):
        app = self.root / "app"
        if app.exists():
            shutil.rmtree(app)
        resources = app / ("Contents/Resources" if platform == "macos" else "resources")
        resources.mkdir(parents=True)
        if packed:
            files = {"manifest.json" if linked else "package.json": self.package}
            create_asar(files, resources / "app.asar", unpacked=list(files) if unpacked else [], symlinks={"package.json": "manifest.json"} if linked else {})
        else:
            (resources / "app").mkdir()
            shutil.copyfile(self.package, resources / "app/package.json")
        if platform == "linux":
            header = bytearray(64)
            header[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<HH", header, 16, 3, 62 if cpu == "x86_64" else 183)
            executable = app / "sample"
        elif platform == "windows":
            header = bytearray(90)
            header[:2] = b"MZ"
            struct.pack_into("<I", header, 60, 64)
            header[64:68] = b"PE\0\0"
            struct.pack_into("<H", header, 68, 0x8664 if cpu == "x86_64" else 0xAA64)
            struct.pack_into("<HH", header, 86, 2, 0x20B)
            executable = app / "sample.exe"
        else:
            header = bytearray(32)
            header[:4] = b"\xcf\xfa\xed\xfe"
            struct.pack_into("<I", header, 4, 0x01000007 if cpu == "x86_64" else 0x0100000C)
            struct.pack_into("<I", header, 12, 2)
            executable = app / "Contents/MacOS/sample"
            executable.parent.mkdir()
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
                "CFBundleExecutable": "sample", "CFBundleIdentifier": "org.example.sample",
                "CFBundleName": "Sample", "CFBundleShortVersionString": "1.2.3", "CFBundleVersion": "1.2.3.7",
            }))
        executable.write_bytes(header)
        executable.chmod(0o755)
        return app, executable

    def check(self, app, platform="linux", cpu="x86_64", **kwargs):
        validate(app, self.package, platform, cpu, "sample", "Sample", "org.example.sample", build_number="7", **kwargs)

    def test_plain_packed_linked_and_unpacked_manifests(self):
        for platform in ("linux", "windows", "macos"):
            for cpu in ("x86_64", "aarch64"):
                for packed, unpacked, linked in ((False, False, False), (True, False, False), (True, True, True)):
                    with self.subTest(platform=platform, cpu=cpu, packed=packed, unpacked=unpacked):
                        app, _ = self.fixture(platform, cpu, packed, unpacked, linked)
                        before = {str(path.relative_to(app)): (path.read_bytes(), path.stat().st_mode) for path in app.rglob("*") if path.is_file()}
                        self.check(app, platform, cpu)
                        self.assertEqual(before, {str(path.relative_to(app)): (path.read_bytes(), path.stat().st_mode) for path in app.rglob("*") if path.is_file()})
                        with self.assertRaisesRegex(ValueError, "CPU differs"):
                            self.check(app, platform, "aarch64" if cpu == "x86_64" else "x86_64")

    def test_macos_zip_preserves_signature_resources_and_framework_links(self):
        app, _ = self.fixture("macos", "aarch64", packed=True)
        signature = app / "Contents/_CodeSignature/CodeResources"
        signature.parent.mkdir()
        signature.write_bytes(b"opaque signature resources")
        framework = app / "Contents/Frameworks/F.framework"
        (framework / "Versions/A").mkdir(parents=True)
        (framework / "Versions/A/F").write_bytes(b"opaque framework bytes")
        (framework / "Versions/Current").symlink_to("A")
        (framework / "F").symlink_to("Versions/Current/F")
        output = self.root / "signed.zip"
        create_archive(app, "macos", "Sample.app", "zip", 1, output)
        before = hashlib.sha256(output.read_bytes()).digest()
        self.check(output, "macos", "aarch64")
        self.assertEqual(before, hashlib.sha256(output.read_bytes()).digest())
        info = app / "Contents/Info.plist"
        metadata = plistlib.loads(info.read_bytes())
        metadata["CFBundleIdentifier"] = "org.example.other"
        info.write_bytes(plistlib.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "bundle identity differs"):
            self.check(app, "macos", "aarch64")

    def test_mismatched_or_ambiguous_manifest(self):
        for field, value in (("version", "2.0.0"), ("name", "other"), ("main", "other.cjs")):
            app, _ = self.fixture()
            manifest = app / "resources/app/package.json"
            actual = json.loads(manifest.read_text())
            actual[field] = value
            manifest.write_text(json.dumps(actual))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity differs"):
                self.check(app)
        app, _ = self.fixture(packed=True)
        (app / "resources/app").mkdir()
        shutil.copyfile(self.package, app / "resources/app/package.json")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.check(app)

    def test_corrupt_archive_and_executable_fail_closed(self):
        app, binary = self.fixture("windows")
        data = bytearray(binary.read_bytes())
        struct.pack_into("<I", data, 60, 0xFFFFFFFF)
        binary.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Truncated"):
            self.check(app, "windows")
        app, binary = self.fixture()
        binary.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "executable mode"):
            self.check(app)
        app, _ = self.fixture(packed=True)
        archive = app / "resources/app.asar"
        archive.write_bytes(archive.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "manifest offset"):
            self.check(app)
        app, _ = self.fixture(packed=True, unpacked=True)
        (app / "resources/app.asar.unpacked/package.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "sidecar size mismatch"):
            self.check(app)

    def test_universal_macos_requires_matching_real_slice(self):
        app, binary = self.fixture("macos")
        x64 = binary.read_bytes()
        arm = bytearray(x64)
        struct.pack_into("<I", arm, 4, 0x0100000C)
        universal = bytearray(48)
        struct.pack_into(">II", universal, 0, 0xCAFEBABE, 2)
        struct.pack_into(">IIIII", universal, 8, 0x01000007, 3, 48, 32, 0)
        struct.pack_into(">IIIII", universal, 28, 0x0100000C, 0, 80, 32, 0)
        binary.write_bytes(universal + x64 + arm)
        self.check(app, "macos", "x86_64")
        self.check(app, "macos", "aarch64")
        struct.pack_into(">I", universal, 28, 0x01000007)
        binary.write_bytes(universal + x64 + arm)
        with self.assertRaisesRegex(ValueError, "universal Mach-O slice"):
            self.check(app, "macos", "aarch64")


if __name__ == "__main__":
    unittest.main()
