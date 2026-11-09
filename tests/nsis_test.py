from pathlib import Path
import json
import tempfile
import struct
import unittest

from electron.private.nsis import build_installer, installer_script, literal


class NsisTest(unittest.TestCase):
    def test_installation_scope_separates_registry_and_ownership(self):
        user = self.render(protocols=["sample"], file_associations={".sample": "Sample"})
        machine = self.render(installation_scope="machine", protocols=["sample"], file_associations={".sample": "Sample"})
        self.assertIn('RequestExecutionLevel admin', machine)
        self.assertIn('SetShellVarContext all', machine)
        self.assertIn('InstallDir "$PROGRAMFILES64\\org.example.sample"', machine)
        self.assertIn('WriteRegStr HKLM ', machine)
        self.assertNotIn(' HKCU ', machine)
        self.assertIn('RequestExecutionLevel user', user)
        self.assertIn('SetShellVarContext current', user)
        self.assertIn('WriteRegStr HKCU ', user)
        self.assertNotIn(' HKLM ', user)
        for script, scope in [(user, "user"), (machine, "machine")]:
            self.assertIn('"app" "scope" "' + scope + '"', script)
            self.assertLess(script.index('Abort "Installation scope mismatch."', script.index('owned:')),
                            script.index('ExecWait'))
        self.assertIn('StrCmp $0 "" install_scope_ok', user)
        self.assertNotIn('StrCmp $0 "" install_scope_ok', machine)
        for options in ({"installation_scope": "other"},
                        {"installation_scope": "machine", "updater_cache_name": "sample-updater"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.render(**options)

    def test_tracked_empty_directories_install_and_uninstall_without_recursive_removal(self):
        manifest = self.root / "directories.json"
        manifest.write_text(json.dumps(["cache/empty", ".hidden"]))
        for compression in ("zlib", "7z"):
            script = self.render(directory_manifest=str(manifest), compression=compression,
                                 payload_archive=str(self.root / "payload.7z") if compression == "7z" else "")
            for name in ("cache\\empty", ".hidden"):
                self.assertIn('CreateDirectory "$INSTDIR\\' + name + '"', script)
                self.assertIn('RMDir "$INSTDIR\\' + name + '"', script)
            self.assertNotIn('RMDir /r', script)
        for paths in (["../escape"], ["sample.exe/child"], ["Uninstall.exe/child"], ["CACHE", "cache/empty"]):
            manifest.write_text(json.dumps(paths))
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.render(directory_manifest=str(manifest))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "sample.exe").write_bytes(b"payload")
        self.package = self.root / "package.json"
        self.package.write_text('{"version":"1.2.3"}')

    def render(self, **kwargs):
        return installer_script(self.app, self.package, "org.example.sample", "Sample", "sample", self.root / "setup.exe", **kwargs)

    def test_rejects_unsafe_payloads_before_compilation(self):
        for name in ["Uninstall.exe", ".rules-electron.ini", "bad${__FILE__}", "SAMPLE.exe", "CON"]:
            file = self.app / name
            file.write_bytes(b"bad")
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.render()
            file.unlink()
        (self.app / "link").symlink_to(self.package)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.render()

    def test_literal_dollars_cannot_expand_runtime_variables(self):
        self.assertEqual(literal('Price $5 "quoted"'), '"Price $$5 $\\"quoted$\\""')
        for value in ["${NSISDIR}", "$%HOME%", "line\n!system command", "nul\0"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                literal(value)

    def test_updater_cache_and_version_constraints(self):
        (self.app / "resources").mkdir()
        (self.app / "resources/app-update.yml").write_text('{"updaterCacheDirName":"other"}')
        with self.assertRaisesRegex(ValueError, "cache must match"):
            self.render(updater_cache_name="expected")
        self.package.write_text('{"version":"65536.0.0"}')
        with self.assertRaisesRegex(ValueError, "0..65535"):
            self.render()

    def test_build_identity_keeps_product_release_separate(self):
        script = self.render(build_number="7")
        self.assertIn('VIProductVersion 1.2.3.7', script)
        self.assertIn('VIAddVersionKey "FileVersion" "1.2.3.7"', script)
        self.assertIn('VIAddVersionKey "ProductVersion" "1.2.3"', script)
        self.assertIn('"DisplayVersion" "1.2.3"', script)
        script = self.render(build_version="4.5.6.8", build_number="7")
        self.assertIn('VIProductVersion 4.5.6.8', script)
        with self.assertRaisesRegex(ValueError, "0..65535"):
            self.render(build_number="65536")

    def test_rejects_wrong_payload_cpu_before_invoking_compiler(self):
        header = bytearray(70)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 60, 64)
        header[64:68] = b"PE\0\0"
        struct.pack_into("<H", header, 68, 0xaa64)
        (self.app / "sample.exe").write_bytes(header)
        with self.assertRaisesRegex(ValueError, "architecture mismatch"):
            build_installer({
                "app": str(self.app), "package_json": str(self.package),
                "app_id": "org.example.sample", "product_name": "Sample", "executable_name": "sample",
                "compiler": str(self.root / "unavailable"), "data": str(self.root), "architecture": "x64",
            }, self.root / "setup.exe", self.root / "setup.nsi")

    def test_file_association_inputs_reject_registry_and_script_injection(self):
        for associations in [
            {"sample": "Document"}, {".Sample": "Document"}, {".sample\\shell": "Document"},
            {".sample.other": "Document"}, {".sample": ""}, {".sample": "${NSISDIR}"},
            {".sample": "line\nbreak"},
        ]:
            with self.subTest(associations=associations), self.assertRaises(ValueError):
                self.render(file_associations=associations)

    def test_document_icons_reject_unregistered_missing_unsafe_or_invalid_inputs(self):
        source = self.app / "document.ico"
        source.write_bytes(b"not an ICO")
        for extension, name in [
            (".other", "document.ico"), (".sample", "missing.ico"),
            (".sample", "../document.ico"), (".sample", "/document.ico"),
            (".sample", "./document.ico"), (".sample", "folder/../document.ico"),
            (".sample", "document.ico"), (".sample", "sample.exe"),
        ]:
            with self.subTest(extension=extension, name=name), self.assertRaises(ValueError):
                self.render(file_associations={".sample": "Document"}, file_association_icons={extension: name})
        self.assertEqual(source.read_bytes(), b"not an ICO")

    def test_file_association_order_is_deterministic(self):
        first = self.render(file_associations={".second": "Second", ".first": "First"})
        second = self.render(file_associations={".first": "First", ".second": "Second"})
        self.assertEqual(first, second)

    def test_extra_file_verbs_keep_open_default_and_replace_owned_commands(self):
        options = {"file_associations": {".sample": "Sample"},
                   "file_association_verbs": {".sample": ["print", "edit"]},
                   "file_association_verb_labels": {"edit": 'Edit $5 "document"'}}
        first = self.render(**options)
        second = self.render(**dict(options, file_association_verbs={".sample": ["edit", "print"]}))
        self.assertEqual(first, second)
        for scope, hive in (("user", "HKCU"), ("machine", "HKLM")):
            script = self.render(**options, installation_scope=scope)
            commands = [line for line in script.splitlines() if line.startswith("WriteRegStr " + hive)
                        and "\\shell\\" in line and "\\command" in line]
            self.assertTrue(any(line.endswith('\'"$INSTDIR\\sample.exe" "%1"\'') for line in commands))
            for verb in ("edit", "print"):
                self.assertTrue(any("\\shell\\" + verb + "\\command" in line
                                    and line.endswith('\'"$INSTDIR\\sample.exe" --file-association-verb=' + verb + ' "%1"\'')
                                    for line in commands))
            self.assertIn('\\shell" "" "open"', script)
            self.assertIn(literal('Edit $5 "document"'), script)
            cleanup = next(line for line in script.splitlines() if line.startswith("DeleteRegKey " + hive) and line.endswith('\\shell"'))
            self.assertLess(script.index('file_type_ok_0:'), script.index(cleanup))
            self.assertLess(script.index(cleanup), script.index('\\shell\\edit\\command'))

    def test_extra_file_verbs_reject_unregistered_names_and_script_injection(self):
        for verbs in ({".other": ["edit"]}, {".sample": ["open"]}, {".sample": ["Edit"]},
                      {".sample": ["edit", "edit"]}, {".sample": ["edit\\command"]},
                      {".sample": ["${NSISDIR}"]}, {".sample": ["edit\nprint"]}):
            with self.subTest(verbs=verbs), self.assertRaises(ValueError):
                self.render(file_associations={".sample": "Sample"}, file_association_verbs=verbs)
        for labels in ({"other": "Other"}, {"edit": ""}, {"edit": "${NSISDIR}"}, {"edit": "line\nbreak"}):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                self.render(file_associations={".sample": "Sample"},
                            file_association_verbs={".sample": ["edit"]}, file_association_verb_labels=labels)

    def test_app_user_model_id_constraints(self):
        for value in ["contains space", "tabs\there", "a" * 129, "😀" * 65, "${NSISDIR}"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.render(app_user_model_id=value)
        self.render(app_user_model_id="a" * 128)
        self.render(app_user_model_id="😀" * 64)

    def test_malformed_installer_icons_fail_before_compilation(self):
        icon = self.root / "invalid.ico"
        for content in [b"not an ICO", struct.pack("<HHH", 0, 1, 1)]:
            icon.write_bytes(content)
            for option in ["installer_icon", "uninstaller_icon"]:
                with self.subTest(content=content, option=option), self.assertRaisesRegex(ValueError, "ICO"):
                    self.render(**{option: str(icon)})


if __name__ == "__main__":
    unittest.main()
