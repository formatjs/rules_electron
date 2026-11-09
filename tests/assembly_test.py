"""Behavior checks for distribution layout and rejected manifests."""

import json
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from electron.private.assemble import assemble


class AssemblyTest(unittest.TestCase):
    def test_generated_link_manifest_keeps_asar_and_resource_namespaces_separate(self):
        tree = self.root / "generated"
        tree.mkdir()
        (tree / "payload").write_bytes(b"generated")
        links = self.root / "links.json"
        links.write_text('{"alias":"payload"}')
        entry = {"source": str(tree), "path": "resources/app/generated", "directory": True, "symlink_manifest": str(links)}
        output = self.root / "generated-app"
        assemble(self.entries + [entry, dict(entry, path="resources/generated")], output, asar=True)
        data = (output / "resources/app.asar").read_bytes()
        length = struct.unpack_from("<I", data, 12)[0]
        self.assertEqual(json.loads(data[16:16 + length])["files"]["generated"]["files"]["alias"], {"link": "generated/payload"})
        self.assertEqual((output / "resources/generated/alias").read_bytes(), b"generated")
        for name, entries, options in [
            ("plain", self.entries + [entry], {}),
            ("windows", self.entries + [dict(entry, path="resources/generated")], {"platform": "windows", "asar": True}),
            ("duplicate", self.entries + [entry], {"asar": True, "asar_symlinks": {"generated/alias": "main.js"}}),
            ("extra", self.entries, {"asar": True, "extra_files": [dict(entry, path="extra")]}),
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                assemble(entries, self.root / name, **options)
            self.assertFalse((self.root / name).exists())

    def test_resource_directory_links_preserve_aliases_after_relocation(self):
        entries = self.entries + [{"source": str(self.main), "path": "resources/versions/v1/payload"}]
        output = self.root / "linked"
        assemble(entries, output, asar=True, resource_symlinks={"current": "versions/v1", "nested/alias": "current"})
        moved = self.root / "relocated"
        output.rename(moved)
        self.assertEqual((moved / "resources/current").readlink().as_posix(), "versions/v1")
        self.assertEqual((moved / "resources/nested/alias").readlink().as_posix(), "../current")
        self.assertEqual((moved / "resources/nested/alias/payload").read_bytes(), b"app")
        (moved / "resources/versions/v1/payload").write_bytes(b"changed")
        self.assertEqual((moved / "resources/current/payload").read_bytes(), b"changed")
        self.assertTrue((moved / "resources/app.asar").is_file())

    def test_resource_links_reject_collisions_escapes_cycles_and_app_paths_before_writing(self):
        entries = self.entries + [{"source": str(self.main), "path": "resources/data/payload"}]
        invalid = [{"../escape": "data"}, {"alias": "../outside"}, {"alias": "missing"},
                   {"one": "two", "two": "one"}, {"data": "data"},
                   {"app/alias": "data"}, {"alias": "app/main.js"}, {"data/payload": "data"},
                   {"root": "", "alias": "root/app/main.js"}]
        for links in invalid:
            with self.subTest(links=links), self.assertRaises(ValueError):
                assemble(entries, self.root / "invalid-links", resource_symlinks=links)
        self.assertFalse((self.root / "invalid-links").exists())
        with self.assertRaisesRegex(ValueError, "require Linux or macOS"):
            assemble(entries, self.root / "windows-links", platform="windows", resource_symlinks={"alias": "data"})

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runtime = self.root / "runtime"
        self.runtime.write_bytes(b"runtime")
        self.package = self.root / "package.json"
        self.package.write_text(json.dumps({"main": "main.js"}))
        self.main = self.root / "main.js"
        self.main.write_bytes(b"app")
        self.entries = [
            {"source": str(self.runtime), "path": "electron", "executable": True},
            {"source": str(self.package), "path": "resources/app/package.json"},
            {"source": str(self.main), "path": "resources/app/main.js"},
        ]

    def test_relocatable_layout_and_normalized_metadata(self):
        output = self.root / "distribution"
        assemble(self.entries, output)
        moved = self.root / "moved"
        output.rename(moved)
        for path, content, mode in [
            ("electron", b"runtime", 0o755),
            ("resources/app/main.js", b"app", 0o644),
        ]:
            file = moved / path
            self.assertEqual(file.read_bytes(), content)
            self.assertEqual(file.stat().st_mode & 0o777, mode)
            self.assertEqual(file.stat().st_mtime, 0)
            self.assertFalse(file.is_symlink())

    def test_rejects_invalid_destinations_before_writing(self):
        for path in ["../escape", "/absolute", "a//b", "a/./b", "a/../b", "a\\b", "C:/file", "", "."]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                assemble(self.entries + [{"source": str(self.main), "path": path}], self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_rejects_duplicate_and_overlapping_destinations(self):
        for path in ["electron", "electron/child", "resources", "resources/app.asar"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                assemble(self.entries + [{"source": str(self.main), "path": path}], self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_missing_or_escaping_entry_point(self):
        for main in ["missing.js", "../main.js"]:
            self.package.write_text(json.dumps({"main": main}))
            with self.subTest(main=main), self.assertRaises(ValueError):
                assemble(self.entries, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_asar_entry_point_resolves_file_and_directory_links(self):
        for main in ["entry.js", "root/main.js"]:
            self.package.write_text(json.dumps({"main": main}))
            output = self.root / main.replace("/", "-")
            assemble(self.entries, output, asar=True, asar_symlinks={"entry.js": "main.js", "root": ""})
            data = (output / "resources/app.asar").read_bytes()
            length = struct.unpack_from("<I", data, 12)[0]
            files = json.loads(data[16:16 + length])["files"]
            self.assertEqual(files["entry.js"], {"link": "main.js"})
            self.assertEqual(files["root"], {"link": ""})
            self.assertIn("main.js", files)
        self.package.write_text(json.dumps({"main": "root"}))
        with self.assertRaisesRegex(ValueError, "App entry point missing"):
            assemble(self.entries, self.root / "directory-entry", asar=True, asar_symlinks={"root": ""})
        self.assertFalse((self.root / "directory-entry").exists())

    def test_asar_preserves_content_and_unpacked_native_files(self):
        self.package.write_text(json.dumps({"main": "main.js", "scripts": {"build": "private development command"}}))
        self.main.write_text("console.log('世界')", encoding="utf-8")
        empty = self.root / "empty"
        empty.write_bytes(b"")
        entries = self.entries + [
            {"source": str(self.runtime), "path": "resources/app/node_modules/example/addon.node"},
            {"source": str(empty), "path": "resources/app/empty"},
            {"source": str(self.main), "path": "resources/config/settings.json"},
        ]
        output = self.root / "first"
        assemble(entries, output, asar=True,
                 asar_unpacked=["node_modules/example/addon.node"], remove_package_scripts=True)
        archive = (output / "resources/app.asar").read_bytes()
        size_size, header_size, payload_size, json_size = struct.unpack("<IIII", archive[:16])
        self.assertEqual(size_size, 4)
        self.assertEqual(payload_size + 4, header_size)
        header = json.loads(archive[16:16 + json_size])

        def contents(entry):
            start = 8 + header_size + int(entry["offset"])
            return archive[start:start + entry["size"]]

        main = header["files"]["main.js"]
        self.assertEqual(contents(main), self.main.read_bytes())
        self.assertEqual(main["integrity"]["hash"], hashlib.sha256(self.main.read_bytes()).hexdigest())
        self.assertEqual(contents(header["files"]["empty"]), b"")
        self.assertNotIn("scripts", json.loads(contents(header["files"]["package.json"])))
        addon = header["files"]["node_modules"]["files"]["example"]["files"]["addon.node"]
        self.assertTrue(addon["unpacked"])
        self.assertNotIn("offset", addon)
        self.assertEqual((output / "resources/app.asar.unpacked/node_modules/example/addon.node").read_bytes(), b"runtime")
        self.assertEqual((output / "resources/config/settings.json").read_bytes(), self.main.read_bytes())
        self.assertFalse((output / "resources/app").exists())
        second = self.root / "second"
        assemble(list(reversed(entries)), second, asar=True,
                 asar_unpacked=["node_modules/example/addon.node"], remove_package_scripts=True)
        self.assertEqual(archive, (second / "resources/app.asar").read_bytes())

    def test_rejects_missing_unpacked_paths_and_inconsistent_fuses(self):
        for options in [
            {"asar_unpacked": ["main.js"]},
            {"asar": True, "asar_unpacked": ["missing.node"]},
            {"asar": True, "asar_unpacked": ["../escape"]},
            {"fuses": {"onlyLoadAppFromAsar": "on"}},
            {"fuses": {"enableEmbeddedAsarIntegrityValidation": "on"}, "platform": "macos"},
            {"asar": True, "fuses": {"enableEmbeddedAsarIntegrityValidation": "on"}},
            {"asar": True, "fuses": {"enableEmbeddedAsarIntegrityValidation": "on"}, "platform": "windows"},
            {"windows_metadata": {"CompanyName": "Example"}, "platform": "windows"},
            {"windows_metadata": {"CompanyName": "Example"}},
            {"windows_icon": "example.ico", "platform": "windows"},
            {"windows_icon": "example.ico"},
            {"asar_symlinks": {"linked-main.js": "main.js"}},
            {"asar_unpacked_patterns": ["**/*.node"]},
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                assemble(self.entries, self.root / "out", **options)
        self.assertFalse((self.root / "out").exists())

    def test_generated_tree_expansion_and_collisions(self):
        bundle = self.root / "bundle"
        (bundle / "assets").mkdir(parents=True)
        (bundle / "index.html").write_text("<h1>Example</h1>")
        (bundle / "assets/style.css").write_text("body { margin: 0 }")
        entry = {"source": str(bundle), "path": "resources/app/renderer", "directory": True}
        output = self.root / "valid"
        assemble(self.entries + [entry], output)
        self.assertEqual((output / "resources/app/renderer/assets/style.css").read_text(), "body { margin: 0 }")
        conflict = {"source": str(self.main), "path": "resources/app/renderer/index.html"}
        with self.assertRaisesRegex(ValueError, "Duplicate destination"):
            assemble(self.entries + [entry, conflict], self.root / "conflict")
        (bundle / "projected.js").symlink_to(self.main)
        assemble(self.entries + [entry], self.root / "projected")
        projected = self.root / "projected/resources/app/renderer/projected.js"
        self.assertEqual(projected.read_bytes(), b"app")
        self.assertFalse(projected.is_symlink())
        (bundle / "escape").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Directory symlinks"):
            assemble(self.entries + [entry], self.root / "symlink")
        self.assertFalse((self.root / "conflict").exists())
        self.assertFalse((self.root / "symlink").exists())

    def test_empty_app_and_extra_directories_survive_plain_and_asar_assembly(self):
        tree = self.root / "empty-tree"
        (tree / "nested/empty").mkdir(parents=True)
        entry = {"source": str(tree), "path": "resources/app/assets", "directory": True}
        extra = [{"source": str(tree), "path": "extra", "directory": True}]
        for asar in (False, True):
            output = self.root / str(asar)
            assemble(self.entries + [entry], output, asar=asar, extra_files=extra)
            self.assertTrue((output / "extra/nested/empty").is_dir())
            self.assertEqual(list((output / "extra/nested/empty").iterdir()), [])
            if asar:
                data = (output / "resources/app.asar").read_bytes()
                length = struct.unpack_from("<I", data, 12)[0]
                files = json.loads(data[16:16 + length])["files"]
                self.assertEqual(files["assets"]["files"]["nested"]["files"]["empty"], {"files": {}})
            else:
                directory = output / "resources/app/assets/nested/empty"
                self.assertTrue(directory.is_dir())
                self.assertEqual((directory.stat().st_mode & 0o777, directory.stat().st_mtime), (0o755, 0))
        conflict = {"source": str(self.main), "path": "resources/app/assets"}
        with self.assertRaisesRegex(ValueError, "collision"):
            assemble(self.entries + [entry, conflict], self.root / "bad-empty")
        self.assertFalse((self.root / "bad-empty").exists())


if __name__ == "__main__":
    unittest.main()
