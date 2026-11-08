import json
import hashlib
from pathlib import Path
import plistlib
import stat
import struct
import tempfile
import unittest
import zlib
from zipfile import ZipFile, ZipInfo

from electron.private.assemble import assemble
from electron.private.asar import create_archive
from electron.private.fuses import SENTINEL
from electron.private.mac_sign import archive_bundle
from electron.private.runtime import extract_runtime


class PlatformLayoutTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package.json"
        self.package.write_text(json.dumps({"main": "main.cjs", "version": "1.2.3"}))
        self.main = self.root / "main.cjs"
        self.main.write_text("module.exports = 42")

    def manifest(self, prefix):
        return [
            {"source": str(self.package), "path": prefix + "/app/package.json"},
            {"source": str(self.main), "path": prefix + "/app/main.cjs"},
        ]

    def test_windows_executable_and_asar_layout(self):
        runtime = self.root / "windows.zip"
        with ZipFile(runtime, "w") as archive:
            archive.writestr("electron.exe", b"runtime")
            archive.writestr("icudtl.dat", b"data")
            archive.writestr("locales/en-US.pak", b"english")
            archive.writestr("locales/fr.pak", b"french")
        output = self.root / "app"
        assemble(self.manifest("resources"), output, platform="windows", runtime_archive=runtime,
                 executable_name="sample", asar=True, runtime_languages=["en-US"])
        self.assertEqual((output / "sample.exe").read_bytes(), b"runtime")
        self.assertFalse((output / "electron.exe").exists())
        self.assertTrue((output / "resources/app.asar").is_file())
        self.assertEqual((output / "locales/en-US.pak").read_bytes(), b"english")
        self.assertFalse((output / "locales/fr.pak").exists())

    def macos_runtime(self, icon_metadata=False):
        runtime = self.root / "macos.zip"
        with ZipFile(runtime, "w") as archive:
            for name in ["", "/Frameworks/Electron Helper.app"]:
                prefix = "Electron.app/Contents" + name + ("/Contents" if name else "")
                executable = "Electron Helper" if name else "Electron"
                metadata = {"CFBundleIdentifier": "org.example.helper"} if name else {"CFBundleExecutable": executable}
                if icon_metadata:
                    metadata.update(CFBundleIconFile="electron.icns", CFBundleIconName="electron")
                archive.writestr(prefix + "/Info.plist", plistlib.dumps(metadata))
                archive.writestr(prefix + "/MacOS/" + executable, b"runtime")
            prefix = "Electron.app/Contents/Frameworks/Foo.framework/"
            archive.writestr(prefix + "Versions/A/Foo", b"framework")
            for path, target in [("Versions/Current", "A"), ("Foo", "Versions/Current/Foo")]:
                info = ZipInfo(prefix + path)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, target)
            archive.writestr("LICENSE", b"runtime license")
            archive.writestr("Electron.app/Contents/Frameworks/Electron Framework.framework/Electron Framework",
                             b"framework" + SENTINEL + b"\x01\x09111100111")
        return runtime

    def test_macos_branding_framework_links_and_archive(self):
        runtime = self.macos_runtime()
        output = self.root / "app"
        assemble(self.manifest("Contents/Resources"), output, platform="macos", runtime_archive=runtime,
                 executable_name="sample", product_name="Sample Desktop", app_id="org.example.sample", asar=True, build_number="7",
                 fuses={"enableEmbeddedAsarIntegrityValidation": "on", "onlyLoadAppFromAsar": "on"})
        metadata = plistlib.loads((output / "Contents/Info.plist").read_bytes())
        self.assertEqual(metadata["CFBundleIdentifier"], "org.example.sample")
        self.assertEqual(metadata["CFBundleVersion"], "1.2.3.7")
        self.assertEqual(metadata["CFBundleShortVersionString"], "1.2.3")
        helper = output / "Contents/Frameworks/Sample Desktop Helper.app/Contents/Info.plist"
        self.assertEqual(plistlib.loads(helper.read_bytes())["CFBundleVersion"], "1.2.3.7")
        asar = (output / "Contents/Resources/app.asar").read_bytes()
        header_length = struct.unpack_from("<I", asar, 12)[0]
        self.assertEqual(metadata["ElectronAsarIntegrity"], {
            "Resources/app.asar": {"algorithm": "SHA256", "hash": hashlib.sha256(asar[16:16 + header_length]).hexdigest()},
        })
        framework = output / "Contents/Frameworks/Electron Framework.framework/Electron Framework"
        self.assertEqual(framework.read_bytes(), b"framework" + SENTINEL + b"\x01\x09111111111")
        self.assertEqual((output / "Contents/MacOS/sample").read_bytes(), b"runtime")
        self.assertTrue((output / "Contents/Frameworks/Sample Desktop Helper.app/Contents/MacOS/Sample Desktop Helper").exists())
        link = output / "Contents/Frameworks/Foo.framework/Foo"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.read_bytes(), b"framework")
        self.assertEqual((output / "Contents/Resources/runtime-licenses/LICENSE").read_bytes(), b"runtime license")
        first, second = self.root / "one.zip", self.root / "two.zip"
        archive_bundle(output, first, "Sample Desktop.app")
        archive_bundle(output, second, "Sample Desktop.app")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with ZipFile(first) as archive:
            info = archive.getinfo("Sample Desktop.app/Contents/Frameworks/Foo.framework/Foo")
            self.assertTrue(stat.S_ISLNK(info.external_attr >> 16))
            self.assertEqual(archive.read(info), b"Versions/Current/Foo")

    def platform_runtime(self, platform):
        if platform == "macos":
            return self.macos_runtime()
        runtime = self.root / (platform + ".zip")
        with ZipFile(runtime, "w") as archive:
            archive.writestr("electron.exe" if platform == "windows" else "electron", b"runtime")
        return runtime

    def test_extra_files_follow_content_root_and_stay_outside_asar(self):
        notice = self.root / "notice.txt"
        notice.write_bytes(b"Example notice\n")
        tree = self.root / "support"
        (tree / "nested").mkdir(parents=True)
        tool = tree / "nested/tool"
        tool.write_bytes(b"helper")
        tool.chmod(0o751)
        (tree / ".metadata").write_bytes(b"")
        for platform in ("linux", "windows", "macos"):
            with self.subTest(platform=platform):
                resources = "Contents/Resources" if platform == "macos" else "resources"
                output = self.root / (platform + "-app")
                assemble(self.manifest(resources), output, platform=platform,
                         runtime_archive=self.platform_runtime(platform), app_id="org.example.sample", asar=True,
                         extra_files=[{"source": str(notice), "path": "licenses/NOTICE.txt"},
                                      {"source": str(tree), "path": "support", "directory": True}])
                relocated = self.root / (platform + "-relocated")
                output.rename(relocated)
                content = relocated / "Contents" if platform == "macos" else relocated
                self.assertEqual((content / "licenses/NOTICE.txt").read_bytes(), b"Example notice\n")
                self.assertEqual((content / "support/nested/tool").read_bytes(), b"helper")
                self.assertEqual((content / "support/nested/tool").stat().st_mode & 0o777, 0o755)
                self.assertEqual((content / "support/.metadata").stat().st_size, 0)
                self.assertEqual((content / "licenses/NOTICE.txt").stat().st_mtime, 0)
                archive = (relocated / resources / "app.asar").read_bytes()
                length = struct.unpack_from("<I", archive, 12)[0]
                self.assertEqual(set(json.loads(archive[16:16 + length])["files"]), {"main.cjs", "package.json"})

    def test_extra_files_reject_app_and_runtime_collisions(self):
        for platform in ("linux", "windows", "macos"):
            resources = "Resources" if platform == "macos" else "resources"
            app_resources = "Contents/Resources" if platform == "macos" else "resources"
            runtime_binary = "MacOS/Electron" if platform == "macos" else "electron.exe" if platform == "windows" else "electron"
            invalid = [resources + "/app/hidden.cjs", resources + "/app.asar",
                       resources + "/app.asar.unpacked/addon.node", runtime_binary, "../escape"]
            if platform == "windows":
                invalid += ["Resources/App/hidden.cjs", "Electron.EXE", "ELECTRON.EXE/child"]
            for index, path in enumerate(invalid):
                with self.subTest(platform=platform, path=path), self.assertRaises(ValueError):
                    assemble(self.manifest(app_resources), self.root / f"invalid-{platform}-{index}",
                             platform=platform, runtime_archive=self.platform_runtime(platform), app_id="org.example.sample",
                             extra_files=[{"source": str(self.main), "path": path}])
        with self.assertRaisesRegex(ValueError, "Executable destination already occupied"):
            assemble(self.manifest("Contents/Resources"), self.root / "occupied.app", platform="macos",
                     runtime_archive=self.macos_runtime(), app_id="org.example.sample", executable_name="sample",
                     extra_files=[{"source": str(self.main), "path": "MacOS/sample"}])
        with self.assertRaisesRegex(ValueError, "Executable destination already occupied"):
            assemble(self.manifest("resources"), self.root / "occupied-windows", platform="windows",
                     runtime_archive=self.platform_runtime("windows"), executable_name="sample",
                     extra_files=[{"source": str(self.main), "path": "SAMPLE.EXE"}])

    def icns_fixture(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress((b"\0" + b"\x2b\x2b\x2b\xff" * 32) * 32)) + chunk(b"IEND", b""))
        icon = self.root / "example.icns"
        icon.write_bytes(b"icns" + struct.pack(">I", 16 + len(png)) + b"ic11" + struct.pack(">I", 8 + len(png)) + png)
        return icon

    def test_macos_icon_brands_main_and_helper_before_archive(self):
        icon = self.icns_fixture()
        output = self.root / "icon.app"
        assemble(self.manifest("Contents/Resources"), output, platform="macos",
                 runtime_archive=self.macos_runtime(icon_metadata=True), app_id="org.example.sample", macos_icon=icon)
        for plist in [output / "Contents/Info.plist", *output.glob("Contents/Frameworks/*Helper.app/Contents/Info.plist")]:
            metadata = plistlib.loads(plist.read_bytes())
            self.assertEqual(metadata["CFBundleIconFile"], "app.icns")
            self.assertNotIn("CFBundleIconName", metadata)
            copied = plist.parent / "Resources/app.icns"
            self.assertEqual(copied.read_bytes(), icon.read_bytes())
            self.assertEqual(copied.stat().st_mode & 0o777, 0o644)
        archive = self.root / "icon.zip"
        archive_bundle(output, archive, "Sample.app")
        with ZipFile(archive) as source:
            self.assertEqual(source.read("Sample.app/Contents/Resources/app.icns"), icon.read_bytes())

    def test_macos_icon_rejects_invalid_container_wrong_target_and_collision(self):
        icon = self.icns_fixture()
        with self.assertRaisesRegex(ValueError, "macOS target"):
            assemble([], self.root / "wrong-target", macos_icon=icon)
        with self.assertRaisesRegex(ValueError, "Duplicate destination"):
            assemble(self.manifest("Contents/Resources") + [{"source": str(icon), "path": "Contents/Resources/app.icns"}],
                     self.root / "collision", platform="macos", macos_icon=icon)
        for data in [b"", b"not an icon", b"icns" + struct.pack(">I", 100),
                     b"icns" + struct.pack(">I", 16) + b"ic11" + struct.pack(">I", 100),
                     b"icns" + struct.pack(">I", 16) + b"ic11" + struct.pack(">I", 8)]:
            icon.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                assemble([], self.root / "invalid-icon", platform="macos", macos_icon=icon)
        self.assertFalse((self.root / "invalid-icon").exists())

    def test_windows_icon_rejects_malformed_directory_before_assembly(self):
        icon = self.root / "invalid.ico"
        for data in [b"", struct.pack("<HHH", 0, 2, 1), struct.pack("<HHH", 0, 1, 0),
                     struct.pack("<HHH", 0, 1, 2) + bytes(16),
                     struct.pack("<HHHBBBBHHII", 0, 1, 1, 32, 32, 0, 0, 1, 32, 99, 22),
                     struct.pack("<HHHBBBBHHII", 0, 1, 1, 32, 32, 0, 0, 1, 32, 8, 0)]:
            icon.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                assemble([], self.root / "invalid-windows-icon", platform="windows", windows_icon=icon,
                         windows_resource_tool={"node": "not-invoked"})
        self.assertFalse((self.root / "invalid-windows-icon").exists())

    def test_additional_asar_stages_sidecar_and_header_integrity(self):
        notice = self.root / "extra.txt"
        notice.write_bytes(b"archive sidecar")
        archive = self.root / "shared.asar"
        digest = create_archive({"index.cjs": self.main, "notice.txt": notice}, archive, ["notice.txt"])
        digest_file = self.root / "shared.sha256"
        digest_file.write_text(digest + "\n")
        spec = {"archive": str(archive), "unpacked": str(archive) + ".unpacked",
                "header_hash": str(digest_file), "path": "plugins/shared.asar"}
        for platform in ("linux", "windows", "macos"):
            with self.subTest(platform=platform):
                resources = "Contents/Resources" if platform == "macos" else "resources"
                output = self.root / (platform + "-additional")
                assemble(self.manifest(resources), output, platform=platform,
                         runtime_archive=self.platform_runtime(platform), app_id="org.example.sample", asar=True,
                         extra_asars=[spec])
                self.assertEqual((output / resources / "plugins/shared.asar").read_bytes(), archive.read_bytes())
                self.assertEqual((output / resources / "plugins/shared.asar.unpacked/notice.txt").read_bytes(), b"archive sidecar")
                if platform == "macos":
                    metadata = plistlib.loads((output / "Contents/Info.plist").read_bytes())
                    self.assertEqual(metadata["ElectronAsarIntegrity"]["Resources/plugins/shared.asar"],
                                     {"algorithm": "SHA256", "hash": digest})
                    self.assertEqual(len(metadata["ElectronAsarIntegrity"]), 2)
        for destination in ("../escape.asar", "app.asar", "app/extra.asar", "not-an-archive.txt"):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                assemble(self.manifest("resources"), self.root / "invalid-extra", extra_asars=[dict(spec, path=destination)])
        digest_file.write_text("0" * 64)
        with self.assertRaisesRegex(ValueError, "header digest mismatch"):
            assemble(self.manifest("resources"), self.root / "bad-digest", extra_asars=[spec])

    def test_macos_protocols_brand_main_bundle_only(self):
        output = self.root / "protocol.app"
        assemble(self.manifest("Contents/Resources"), output, platform="macos",
                 runtime_archive=self.macos_runtime(), app_id="org.example.sample",
                 macos_protocols={"Viewer": ["EXAMPLE+READ", "example.read"], "Editor": ["EXAMPLE"]},
                 macos_protocol_roles={"Viewer": "Viewer"})
        metadata = plistlib.loads((output / "Contents/Info.plist").read_bytes())
        self.assertEqual(metadata["CFBundleURLTypes"], [
            {"CFBundleURLName": "Editor", "CFBundleURLSchemes": ["example"], "CFBundleTypeRole": "Editor"},
            {"CFBundleURLName": "Viewer", "CFBundleURLSchemes": ["example+read", "example.read"], "CFBundleTypeRole": "Viewer"},
        ])
        for helper in output.glob("Contents/Frameworks/*Helper.app/Contents/Info.plist"):
            self.assertNotIn("CFBundleURLTypes", plistlib.loads(helper.read_bytes()))

    def test_macos_extra_plist_preserves_document_metadata_and_source(self):
        extra = {"CFBundleDocumentTypes": [{"CFBundleTypeName": "Sample Document", "CFBundleTypeRole": "Editor",
                                          "LSItemContentTypes": ["org.example.sample.document"]}],
                 "UTExportedTypeDeclarations": [{"UTTypeIdentifier": "org.example.sample.document",
                                                 "UTTypeConformsTo": ["public.data"]}],
                 "NSCameraUsageDescription": "Example camera purpose"}
        source = self.root / "extra.plist"
        source.write_bytes(plistlib.dumps(extra))
        before = source.read_bytes()
        output = self.root / "document.app"
        runtime = self.macos_runtime()
        assemble(self.manifest("Contents/Resources"), output, platform="macos", runtime_archive=runtime,
                 app_id="org.example.sample", executable_name="sample", asar=True, macos_extra_plist=source)
        metadata = plistlib.loads((output / "Contents/Info.plist").read_bytes())
        for key, value in extra.items():
            self.assertEqual(metadata[key], value)
        self.assertEqual(metadata["CFBundleIdentifier"], "org.example.sample")
        self.assertEqual(metadata["CFBundleExecutable"], "sample")
        self.assertIn("Resources/app.asar", metadata["ElectronAsarIntegrity"])
        for helper in output.glob("Contents/Frameworks/*Helper.app/Contents/Info.plist"):
            self.assertTrue(extra.keys().isdisjoint(plistlib.loads(helper.read_bytes())))
        archive = self.root / "document.zip"
        archive_bundle(output, archive, "Sample.app")
        with ZipFile(archive) as packaged:
            self.assertEqual(plistlib.loads(packaged.read("Sample.app/Contents/Info.plist")), metadata)
        self.assertEqual(source.read_bytes(), before)

    def test_macos_extra_plist_rejects_identity_and_wrong_platform(self):
        source = self.root / "extra.plist"
        runtime = self.macos_runtime()
        for key in ["CFBundleIdentifier", "CFBundleExecutable", "CFBundleVersion", "CFBundleShortVersionString",
                    "CFBundleName", "CFBundleDisplayName", "CFBundleIconFile", "CFBundleIconName",
                    "CFBundlePackageType", "CFBundleURLTypes", "ElectronAsarIntegrity"]:
            source.write_bytes(plistlib.dumps({key: "override"}))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "reserved fields"):
                assemble(self.manifest("Contents/Resources"), self.root / (key + ".app"), platform="macos",
                         runtime_archive=runtime, app_id="org.example.sample", macos_extra_plist=source)
        source.write_bytes(plistlib.dumps([]))
        with self.assertRaisesRegex(ValueError, "must contain a dictionary"):
            assemble(self.manifest("Contents/Resources"), self.root / "array.app", platform="macos",
                     runtime_archive=runtime, app_id="org.example.sample", macos_extra_plist=source)
        with self.assertRaisesRegex(ValueError, "requires a macOS target"):
            assemble([], self.root / "wrong-platform", macos_extra_plist=source)

    def test_macos_protocol_validation(self):
        runtime = self.macos_runtime()
        for index, (protocols, roles) in enumerate([
            ({"Example": []}, {}),
            ({"Example": ["1example"]}, {}),
            ({"Example": ["example://"]}, {}),
            ({"Example": ["Example", "example"]}, {}),
            ({"First": ["example"], "Second": ["EXAMPLE"]}, {}),
            ({"": ["example"]}, {}),
            ({"Example": ["example"]}, {"Example": "Owner"}),
            ({}, {"Missing": "Viewer"}),
        ]):
            with self.subTest(protocols=protocols, roles=roles), self.assertRaises(ValueError):
                assemble(self.manifest("Contents/Resources"), self.root / f"invalid-{index}.app", platform="macos",
                         runtime_archive=runtime, app_id="org.example.sample",
                         macos_protocols=protocols, macos_protocol_roles=roles)
        with self.assertRaisesRegex(ValueError, "macOS target"):
            assemble([], self.root / "linux", macos_protocols={"Example": ["example"]})

    def test_runtime_archive_rejects_traversal_links_and_collisions(self):
        for name, target, occupied in [
            ("../escape", None, {}),
            ("link", "../escape", {}),
            ("parent", None, {Path("parent/child"): {}}),
            ("resources/app.asar", None, {}),
        ]:
            archive = self.root / "invalid.zip"
            with ZipFile(archive, "w") as zip:
                info = ZipInfo(name)
                if target:
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zip.writestr(info, target or b"data")
            with self.subTest(name=name), self.assertRaises(ValueError):
                extract_runtime(archive, self.root / "out", "windows", (), occupied)


if __name__ == "__main__":
    unittest.main()
