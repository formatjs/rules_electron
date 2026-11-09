"""Notarization protocol boundaries; no live Apple account or upload."""

from contextlib import redirect_stderr, redirect_stdout
import base64
import hashlib
import io
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from electron.private.mac_sign import archive_bundle
from electron.private.update import create_feed
from electron.tools import notarize_macos

CLI = str(Path(sys.argv.pop(1)).resolve())
BACKEND_KEY = sys.argv.pop(1)


class NotarizationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / "Example 世界.app"
        contents = self.app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "MacOS/sample").write_bytes(b"signed fixture bytes")
        (contents / "MacOS/sample").chmod(0o755)
        (contents / "Resources/empty").mkdir(parents=True)
        (contents / "Resources/data").write_bytes(b"payload\0bytes")
        (contents / "Resources/current").symlink_to("data")
        (contents / "_CodeSignature").mkdir()
        (contents / "_CodeSignature/CodeResources").write_bytes(b"signed resource seal")
        (contents / "CodeResources").write_bytes(b"old ticket")
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundlePackageType": "APPL", "CFBundleExecutable": "sample",
            "CFBundleIdentifier": "org.example.notary",
        }))
        self.source = self.root / "signed.zip"
        archive_bundle(self.app, self.source, self.app.name)
        self.source_bytes = self.source.read_bytes()
        self.credentials = self.root / "private-key.json"
        self.credentials.write_text('{"private":"do-not-forward"}')
        self.environment = {"NOTARY_API": str(self.credentials), "UNRELATED_SECRET": "do-not-forward"}

    def arguments(self, output):
        return ["--backend", "_main/declared-backend", "--input", str(self.source),
                "--output", str(output), "--api-key-env", "NOTARY_API", "--max-wait-seconds", "37"]

    def invoke(self, effect, name="notarized.zip", success=True):
        output = self.root / name
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.environment), patch.object(notarize_macos, "backend", return_value="declared-backend"), \
                patch.object(notarize_macos.subprocess, "run", side_effect=effect) as request, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status = notarize_macos.main(self.arguments(output))
        self.backend_calls = request.call_count
        self.assertEqual(status, 0 if success else 1)
        self.assertEqual(stdout.getvalue(), "MACOS_NOTARIZED\n" if success else "")
        self.assertEqual(stderr.getvalue(), "" if success else "MACOS_NOTARIZATION_FAILED\n")
        self.assertNotIn("do-not-forward", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn(str(self.credentials), stdout.getvalue() + stderr.getvalue())
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertFalse(list(self.root.glob(".electron-notarize-*")))
        return output

    def accept(self, command, **options):
        self.assertEqual(command[:2], ["declared-backend", "notary-submit"])
        self.assertIn("--wait", command)
        self.assertIn("--staple", command)
        self.assertEqual(command[command.index("--max-wait-seconds") + 1], "37")
        self.assertEqual(command[command.index("--api-key-file") + 1], str(self.credentials))
        self.assertNotIn("NOTARY_API", options["env"])
        self.assertNotIn("UNRELATED_SECRET", options["env"])
        self.assertEqual(options["env"]["PATH"], "")
        self.assertTrue(options["capture_output"])
        bundle = Path(command[-1])
        self.assertFalse((bundle / "Contents/CodeResources").exists())
        (bundle / "Contents/CodeResources").write_bytes(b"fixture service ticket")

    def test_ticket_only_commit_preserves_bundle_and_final_updater_hash(self):
        output = self.invoke(self.accept)
        with ZipFile(output) as archive:
            prefix = self.app.name + "/"
            self.assertEqual(archive.read(prefix + "Contents/CodeResources"), b"fixture service ticket")
            self.assertEqual(archive.read(prefix + "Contents/_CodeSignature/CodeResources"), b"signed resource seal")
            self.assertEqual(archive.read(prefix + "Contents/MacOS/sample"), b"signed fixture bytes")
            self.assertEqual(archive.getinfo(prefix + "Contents/MacOS/sample").external_attr >> 16 & 0o777, 0o755)
            self.assertEqual(archive.read(prefix + "Contents/Resources/current"), b"data")
            self.assertTrue(archive.getinfo(prefix + "Contents/Resources/empty/").is_dir())
        package = self.root / "package.json"
        package.write_text('{"version":"2.0.0"}')
        feed = create_feed(artifacts=[{"source": output, "name": "Example-2.0.0.zip"}],
                           package_json=package, output=self.root / "feed", platform="macos",
                           architecture="arm64", release_date="2026-01-02T03:04:05Z")
        self.assertEqual(feed["files"][0]["sha512"], base64.b64encode(hashlib.sha512(output.read_bytes()).digest()).decode())

    def test_rejection_timeout_and_missing_ticket_never_commit(self):
        for label, effect in [
            ("rejected.zip", subprocess.CalledProcessError(1, "backend", output=b"do-not-forward")),
            ("timeout.zip", subprocess.TimeoutExpired("backend", 37, stderr=b"do-not-forward")),
            ("missing.zip", lambda *_args, **_kwargs: None),
        ]:
            with self.subTest(label=label):
                output = self.invoke(effect, label, success=False)
                self.assertFalse(output.exists())

    def test_changed_sealed_resource_and_file_mode_never_commit(self):
        for mode in (False, True):
            def changed(command, **options):
                self.accept(command, **options)
                bundle = Path(command[-1])
                if mode:
                    (bundle / "Contents/MacOS/sample").chmod(0o644)
                else:
                    (bundle / "Contents/_CodeSignature/CodeResources").write_bytes(b"changed seal")
            output = self.invoke(changed, "mode.zip" if mode else "seal.zip", success=False)
            self.assertFalse(output.exists())

    def test_existing_output_and_competing_writer_are_preserved(self):
        existing = self.root / "existing.zip"
        existing.write_bytes(b"prior release")
        self.invoke(lambda *_args, **_kwargs: self.fail("backend ran"), existing.name, success=False)
        self.assertEqual(existing.read_bytes(), b"prior release")
        self.assertEqual(self.backend_calls, 0)
        competing = self.root / "competing.zip"
        def compete(command, **options):
            self.accept(command, **options)
            competing.write_bytes(b"competing release")
        self.invoke(compete, competing.name, success=False)
        self.assertEqual(competing.read_bytes(), b"competing release")

    def test_ticket_symlink_is_rejected_before_backend(self):
        ticket = self.app / "Contents/CodeResources"
        ticket.unlink()
        ticket.symlink_to("_CodeSignature/CodeResources")
        archive_bundle(self.app, self.source, self.app.name)
        self.source_bytes = self.source.read_bytes()
        output = self.invoke(None, "symlink.zip", success=False)
        self.assertEqual(self.backend_calls, 0)
        self.assertFalse(output.exists())

    def test_backend_is_declared_pinned_rcodesign(self):
        result = subprocess.run([notarize_macos.backend(BACKEND_KEY), "--version"], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b"0.29.0", result.stdout)

    def test_real_declared_cli_rejects_invalid_api_credentials_without_output(self):
        output = self.root / "real-rejected.zip"
        result = subprocess.run([CLI, "--input", str(self.source), "--output", str(output),
                                 "--api-key-env", "NOTARY_API"],
                                env={**os.environ, **self.environment}, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"MACOS_NOTARIZATION_FAILED\n")
        self.assertFalse(output.exists())

    def test_host_backend_path_is_not_a_runfile(self):
        with self.assertRaisesRegex(ValueError, "declared backend"):
            notarize_macos.backend("/usr/bin/rcodesign")


if __name__ == "__main__":
    unittest.main()
