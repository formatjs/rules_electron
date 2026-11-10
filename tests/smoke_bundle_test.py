import os
import json
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from tools.ci.run_native_smoke import extract_variant, prepare_app
from tools.ci.smoke_bundle import build_bundles, build_shard, validate_apps
from tools.ci.smoke_shards import ALL_VARIANTS, SHARDS, archive_name


class SmokeBundleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.entries = []
        for variant in sorted(ALL_VARIANTS):
            target_os = variant.split("_")[0]
            arm64 = "aarch64" in variant
            header = bytearray(70)
            if target_os == "linux":
                header[:4] = b"\x7fELF"
                struct.pack_into("<H", header, 18, 183 if arm64 else 62)
            elif target_os == "macos":
                header[:4] = b"\xcf\xfa\xed\xfe"
                struct.pack_into("<I", header, 4, 0x0100000C)
            else:
                header[:2] = b"MZ"
                struct.pack_into("<I", header, 60, 64)
                header[64:68] = b"PE\0\0"
                struct.pack_into("<H", header, 68, 0xAA64 if arm64 else 0x8664)
            base = self.inputs / variant
            base.mkdir()
            prefix = "Contents/Resources/" if target_os == "macos" else "resources/"
            main = "Contents/MacOS/sample-desktop" if target_os == "macos" else "sample-desktop" + (".exe" if target_os == "windows" else "")
            paths = [main, prefix + "native/helper" + (".exe" if target_os == "windows" else ""), prefix + "app.asar.unpacked/node_modules/example-native/addon.node"]
            paths += [prefix + "app.asar.unpacked/node_modules/example-native/" + name for name in ("classic.node", "bad-abi.node")]
            if target_os == "windows":
                paths.append(prefix + "elevate.exe")
            if target_os == "macos":
                source = base / "release.zip"
                with ZipFile(source, "w") as archive:
                    for path in paths:
                        archive.writestr("Sample Desktop.app/" + path, header)
            else:
                source = base / "app"
                for name in paths:
                    path = source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(header)
                    path.chmod(0o755)
                (source / "data").write_bytes(b"resource\0bytes")
                (source / "data").chmod(0o644)
            entry = {"variant": variant, "source": str(source), "directory": source.is_dir()}
            if source.is_dir():
                directories = base / "directories.json"
                directories.write_text(json.dumps(["resources/cache/empty", ".hidden"]))
                entry["directory_manifest"] = str(directories)
            self.entries.append(entry)
            if variant.endswith("_msvc") or target_os == "linux":
                feed = base / "feed"
                feed.mkdir()
                (feed / "Sample.exe").write_bytes(b"installer fixture bytes\0" + variant.encode())
                (feed / "latest.yml").write_bytes(b"channel fixture bytes\n")
                self.entries.append({"variant": variant, "source": str(feed), "directory": True, "package": True})

    def outputs(self, directory):
        directory.mkdir()
        return {shard: str(directory / archive_name(shard)) for shard in SHARDS}

    def test_dmg_handoff_is_data_even_when_remote_materialization_marks_it_executable(self):
        image = self.inputs / 'release_dmg.dmg'
        image.write_bytes(b'unchanged disk image bytes')
        image.chmod(0o755)
        entries = self.entries + [{'variant': 'macos_aarch64', 'source': str(image), 'directory': False, 'package': True}]
        outputs = self.outputs(self.root / 'executable-input')
        build_bundles(entries, outputs)
        baseline = Path(outputs['macos-arm64']).read_bytes()
        with ZipFile(outputs['macos-arm64']) as archive:
            member = archive.getinfo('macos_aarch64/packages/release_dmg.dmg')
            self.assertEqual(member.external_attr >> 16, stat.S_IFREG | 0o644)
            destination = self.root / 'native'
            extract_variant(archive, destination, 'macos_aarch64')
            extracted = destination / member.filename
            self.assertEqual(extracted.stat().st_mode & 0o777, 0o644)
            self.assertEqual(extracted.read_bytes(), image.read_bytes())
        image.chmod(0o644)
        changed = self.outputs(self.root / 'data-input')
        build_bundles(entries, changed)
        self.assertEqual(Path(changed['macos-arm64']).read_bytes(), baseline)

    def test_linux_zip_apps_keep_architecture_gate_and_native_filesystem_links(self):
        for entry in self.entries:
            if entry.get("package") or not entry["variant"].startswith("linux_"):
                continue
            source = Path(entry["source"])
            output = source.parent / "app.zip"
            with ZipFile(output, "w") as archive:
                for file in source.rglob("*"):
                    if not file.is_file():
                        continue
                    info = ZipInfo("app/" + file.relative_to(source).as_posix())
                    info.external_attr = file.stat().st_mode << 16
                    archive.writestr(info, file.read_bytes())
                info = ZipInfo("app/current")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"resources")
                info = ZipInfo("app/resources/cache/empty/")
                info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
                archive.writestr(info, b"")
            entry.update(source=str(output), directory=False)
        outputs = self.outputs(self.root / "zipped-outputs")
        self.build_independently(self.entries, outputs)
        unpacked = self.root / "zipped-unpacked"
        with ZipFile(outputs["linux-x64"]) as archive:
            extract_variant(archive, unpacked, "linux_x86_64")
        app = prepare_app(unpacked, "linux_x86_64", "linux")
        self.assertEqual((app / "current").readlink().as_posix(), "resources")
        self.assertEqual((app / "current/native/helper").read_bytes(), (app / "resources/native/helper").read_bytes())
        self.assertEqual((app / "sample-desktop").stat().st_mode & 0o777, 0o755)
        self.assertEqual(list((app / "resources/cache/empty").iterdir()), [])

    def test_native_linux_zip_rejects_escaping_links_before_extracting(self):
        root = self.root / "malformed/linux_x86_64"
        root.mkdir(parents=True)
        with ZipFile(root / "app.zip", "w") as archive:
            info = ZipInfo("app/escape")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"../outside")
        with self.assertRaises(ValueError):
            prepare_app(root.parent, "linux_x86_64", "linux")
        self.assertFalse((root / "app").exists())

    def build_independently(self, entries, outputs):
        validation = Path(next(iter(outputs.values()))).parent / "matrix.validated"
        validate_apps(entries, validation)
        for shard, variants in SHARDS.items():
            build_shard([entry for entry in entries if entry["variant"] in variants],
                        outputs[shard], shard, validation)

    def test_shards_keep_exact_bytes_and_modes_without_foreign_variants(self):
        outputs = self.outputs(self.root / "outputs")
        self.build_independently(self.entries, outputs)
        unpacked = self.root / "unpacked"
        unpacked.mkdir()
        seen = set()
        for shard, variants in SHARDS.items():
            with ZipFile(outputs[shard]) as archive:
                self.assertEqual({name.split("/")[0] for name in archive.namelist()}, set(variants))
                for variant in variants:
                    extract_variant(archive, unpacked, variant)
                    seen.add(variant)
                    entry = next(entry for entry in self.entries if entry["variant"] == variant and not entry.get("package"))
                    source = Path(entry["source"])
                    if entry["directory"]:
                        for name in ("resources/cache/empty", ".hidden"):
                            directory = unpacked / variant / "app" / name
                            self.assertTrue(directory.is_dir())
                            self.assertEqual(list(directory.iterdir()), [])
                        for file in source.rglob("*"):
                            if file.is_file():
                                output = unpacked / variant / "app" / file.relative_to(source)
                                self.assertEqual(output.read_bytes(), file.read_bytes())
                                self.assertEqual(output.stat().st_mode & 0o777, file.stat().st_mode & 0o777)
                    else:
                        self.assertEqual((unpacked / variant / "app.zip").read_bytes(), source.read_bytes())
                    if variant.endswith("_msvc") or variant == "linux_x86_64":
                        source = self.inputs / variant / "feed/Sample.exe"
                        output = unpacked / variant / "packages/feed/Sample.exe"
                        self.assertEqual(output.read_bytes(), source.read_bytes())
        self.assertEqual(seen, ALL_VARIANTS - {"linux_aarch64"})

    def test_changed_input_paths_mtimes_and_order_preserve_archive_bytes(self):
        first = self.outputs(self.root / "first")
        build_bundles(self.entries, first)
        relocated = self.root / "relocated inputs"
        shutil.copytree(self.inputs, relocated)
        for path in relocated.rglob("*"):
            os.utime(path, (1234567890, 1234567890))
        entries = []
        for entry in reversed(self.entries):
            changed = dict(entry, source=str(relocated / Path(entry["source"]).relative_to(self.inputs)))
            if entry.get("directory_manifest"):
                changed["directory_manifest"] = str(relocated / Path(entry["directory_manifest"]).relative_to(self.inputs))
            entries.append(changed)
        second = self.outputs(self.root / "second")
        self.build_independently(entries, second)
        for shard in SHARDS:
            self.assertEqual(Path(first[shard]).read_bytes(), Path(second[shard]).read_bytes())

    def test_wrong_architecture_in_build_only_linux_arm64_stops_all_shards(self):
        outputs = self.outputs(self.root / "outputs")
        for name in ("sample-desktop", "resources/app.asar.unpacked/node_modules/example-native/classic.node",
                     "resources/app.asar.unpacked/node_modules/example-native/bad-abi.node"):
            source = self.inputs / "linux_aarch64/app" / name
            original = source.read_bytes()
            data = bytearray(original)
            struct.pack_into("<H", data, 18, 62)
            source.write_bytes(data)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "wrong binary architecture"):
                self.build_independently(self.entries, outputs)
            self.assertFalse(any(Path(path).exists() for path in outputs.values()))
            source.write_bytes(original)

    def test_missing_or_duplicate_app_variant_stops_all_shards(self):
        outputs = self.outputs(self.root / "outputs")
        for entries in (self.entries[1:], self.entries + [self.entries[0]]):
            with self.assertRaisesRegex(ValueError, "exactly seven"):
                self.build_independently(entries, outputs)

    def test_shard_rejects_missing_app_foreign_package_and_unknown_shard(self):
        validation = self.root / "matrix.validated"
        validate_apps(self.entries, validation)
        selected = [entry for entry in self.entries if entry["variant"] == "linux_x86_64"]
        foreign = next(entry for entry in self.entries if entry.get("package") and entry["variant"].startswith("windows"))
        output = self.root / "shard.zip"
        for entries, shard in [(selected[1:], "linux-x64"), (selected + [foreign], "linux-x64"),
                               (selected, "unknown")]:
            with self.subTest(shard=shard), self.assertRaisesRegex(ValueError, "complete shard"):
                build_shard(entries, output, shard, validation)
            self.assertFalse(output.exists())

    def test_missing_or_failed_matrix_validation_prevents_output(self):
        selected = [entry for entry in self.entries if entry["variant"] == "linux_x86_64"]
        validation = self.root / "matrix.validated"
        output = self.root / "shard.zip"
        with self.assertRaises(FileNotFoundError):
            build_shard(selected, output, "linux-x64", validation)
        validation.write_bytes(b"failed\n")
        with self.assertRaisesRegex(ValueError, "architecture validation"):
            build_shard(selected, output, "linux-x64", validation)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
