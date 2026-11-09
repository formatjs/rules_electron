"""Real identity preflight with simulated signing/notary service boundaries."""

from contextlib import redirect_stderr, redirect_stdout
import base64
import hashlib
import io
import os
from pathlib import Path
import plistlib
import ssl
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from electron.private.mac_sign import archive_bundle
from electron.private.update import create_feed
from electron.tools import sign_macos

CLI = str(Path(sys.argv.pop(1)).resolve())
SIGNER_KEY, CRYPTO_KEY = sys.argv[1:3]
del sys.argv[1:3]
SIGNER, CRYPTO = sign_macos.backend(SIGNER_KEY), sign_macos.backend(CRYPTO_KEY)
REAL_RUN = subprocess.run


class MacOSReleaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        empty = self.root / "empty.cnf"
        empty.write_text("")
        self.clean = {"PATH": "", "OPENSSL_CONF": str(empty), "LC_ALL": "C", "TZ": "UTC"}
        self.cert, self.key = self.make_identity("release", "/CN=Release Test/OU=TEAMROOT12")
        self.pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.cert.read_text())).hexdigest()
        self.api = self.root / "private-api.json"
        self.api.write_text('{"private":"never-log-password"}')
        self.environment = {"RELEASE_CERT": str(self.cert), "RELEASE_KEY": str(self.key),
                            "RELEASE_PASSWORD": "never-log-password", "NOTARY_API": str(self.api)}
        self.bundle = self.root / "Example.app"
        (self.bundle / "Contents/MacOS").mkdir(parents=True)
        (self.bundle / "Contents/Resources/empty").mkdir(parents=True)
        (self.bundle / "Contents/Resources/payload").write_bytes(b"unchanged resource")
        (self.bundle / "Contents/Resources/current").symlink_to("payload")
        (self.bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundlePackageType": "APPL", "CFBundleExecutable": "sample",
            "CFBundleIdentifier": "org.example.release",
        }))
        executable = self.bundle / "Contents/MacOS/sample"
        executable.write_bytes(struct.pack("<8I", 0xfeedfacf, 0x100000c, 0, 2, 0, 0, 0, 0))
        executable.chmod(0o755)
        self.source = self.root / "input.zip"
        archive_bundle(self.bundle, self.source, self.bundle.name)
        self.original = self.source.read_bytes()
        self.calls = []

    def make_identity(self, name, subject):
        cert, key = self.root / (name + ".pem"), self.root / (name + ".key")
        REAL_RUN([CRYPTO, "req", "-x509", "-newkey", "rsa:2048", "-days", "1", "-subj", subject,
                  "-addext", "extendedKeyUsage=codeSigning", "-addext", "basicConstraints=critical,CA:FALSE",
                  "-passout", "stdin", "-keyout", str(key), "-out", str(cert)],
                 env=self.clean, input=b"never-log-password\n", check=True, capture_output=True, timeout=30)
        return cert, key

    def arguments(self, output, extra=()):
        return ["--backend", SIGNER_KEY, "--crypto", CRYPTO_KEY, "--input", str(self.source),
                "--output", str(output), "--certificate-env", "RELEASE_CERT", "--key-env", "RELEASE_KEY",
                "--password-env", "RELEASE_PASSWORD", "--ca-file", str(self.cert),
                "--expected-leaf-sha256", self.pin, "--expected-team-id", "TEAMROOT12",
                "--signing-time", "2026-11-09T01:02:03Z", "--timestamp-url", "https://timestamp.example.com/",
                "--api-key-env", "NOTARY_API", *extra]

    def service(self, command, **options):
        if command[0] != SIGNER:
            return REAL_RUN(command, **options)
        self.calls.append(command[1])
        self.assertNotIn("RELEASE_PASSWORD", options["env"])
        self.assertNotIn("NOTARY_API", options["env"])
        self.assertEqual(options["env"]["PATH"], "")
        bundle = Path(command[-1])
        if command[1] == "sign":
            self.assertEqual(command[-2], str(bundle))
            self.assertIn("--for-notarization", command)
            self.assertIn("@main:runtime", command)
            self.assertIn("Contents/MacOS/sample:runtime", command)
            self.assertEqual(command[command.index("--signing-time") + 1], "2026-11-09T01:02:03Z")
            private = Path(command[command.index("--pem-file", command.index("--pem-file") + 1) + 1])
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
            self.assertIn(b"BEGIN PRIVATE KEY", private.read_bytes())
            self.assertNotIn(b"ENCRYPTED", private.read_bytes())
            (bundle / "Contents/MacOS/sample").write_bytes(b"signed Mach-O fixture")
        elif command[1] == "notary-submit":
            self.assertIn("--wait", command)
            self.assertIn("--staple", command)
            self.assertEqual((bundle / "Contents/MacOS/sample").read_bytes(), b"signed Mach-O fixture")
            (bundle / "Contents/CodeResources").write_bytes(b"fixture accepted ticket")
        else:
            self.fail("Unexpected backend operation")

    def invoke(self, name="release.zip", extra=(), environment=None, effect=None, success=True):
        output = self.root / name
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, environment or self.environment), \
                patch.object(sign_macos.subprocess, "run", side_effect=effect or self.service), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status = sign_macos.main(self.arguments(output, extra))
        self.assertEqual(status, 0 if success else 1)
        self.assertEqual(stdout.getvalue(), "MACOS_RELEASED\n" if success else "")
        self.assertEqual(stderr.getvalue(), "" if success else "MACOS_RELEASE_FAILED\n")
        self.assertNotIn("never-log-password", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn(str(self.key), stdout.getvalue() + stderr.getvalue())
        self.assertFalse(list(self.root.glob(".electron-macos-release-*")))
        self.assertFalse(list(self.root.glob(".electron-notarize-*")))
        self.assertEqual(self.source.read_bytes(), self.original)
        return output

    def test_encrypted_key_pinned_identity_sign_then_notarize_and_final_feed(self):
        output = self.invoke()
        self.assertEqual(self.calls, ["sign", "notary-submit"])
        with ZipFile(output) as archive:
            self.assertEqual(archive.read("Example.app/Contents/CodeResources"), b"fixture accepted ticket")
            self.assertEqual(archive.read("Example.app/Contents/Resources/payload"), b"unchanged resource")
        package = self.root / "package.json"
        package.write_text('{"version":"2.0.0"}')
        feed = create_feed(artifacts=[{"source": output, "name": "Example-2.0.0.zip"}], package_json=package,
                           output=self.root / "feed", platform="macos", architecture="arm64",
                           release_date="2026-11-09T01:02:03Z")
        self.assertEqual(feed["files"][0]["sha512"], base64.b64encode(hashlib.sha512(output.read_bytes()).digest()).decode())

    def test_wrong_pin_team_password_key_or_roots_stop_before_signing(self):
        other_cert, other_key = self.make_identity("other", "/CN=Other/OU=TEAMROOT12")
        cases = [
            ("pin.zip", ["--expected-leaf-sha256", "0" * 64], self.environment),
            ("team.zip", ["--expected-team-id", "OTHERTEAM1"], self.environment),
            ("password.zip", [], {**self.environment, "RELEASE_PASSWORD": "wrong"}),
            ("key.zip", [], {**self.environment, "RELEASE_KEY": str(other_key)}),
            ("roots.zip", ["--ca-file", str(other_cert)], self.environment),
        ]
        for name, extra, environment in cases:
            with self.subTest(name=name):
                output = self.invoke(name, extra, environment, success=False)
                self.assertFalse(output.exists())
                self.assertEqual(self.calls, [])

    def test_timestamp_policy_and_signing_time_fail_before_backend(self):
        for i, extra in enumerate([["--timestamp-url", "http://timestamp.example.com/"],
                                   ["--timestamp-url", "https://user:secret@timestamp.example.com/"],
                                   ["--signing-time", "not-a-time"]]):
            output = self.invoke(str(i) + ".zip", extra, success=False)
            self.assertFalse(output.exists())
            self.assertEqual(self.calls, [])

    def test_ambiguous_team_and_subject_newline_cannot_impersonate_team(self):
        for i, subject in enumerate(["/CN=Ambiguous/OU=TEAMROOT12/OU=wrong",
                                     "/CN=Misleading\nOU=TEAMROOT12/OU=wrong"]):
            certificate, key = self.make_identity("subject" + str(i), subject)
            pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()
            environment = {**self.environment, "RELEASE_CERT": str(certificate), "RELEASE_KEY": str(key)}
            output = self.invoke("subject" + str(i) + ".zip", ["--expected-leaf-sha256", pin,
                                 "--ca-file", str(certificate)], environment, success=False)
            self.assertFalse(output.exists())
            self.assertEqual(self.calls, [])

    def test_signing_or_notary_failure_never_commits(self):
        for operation in ("sign", "notary-submit"):
            self.calls.clear()
            def failed(command, **options):
                if command[0] == SIGNER and command[1] == operation:
                    self.calls.append(command[1])
                    raise subprocess.CalledProcessError(1, command, stderr=b"never-log-password")
                return self.service(command, **options)
            output = self.invoke(operation + ".zip", effect=failed, success=False)
            self.assertFalse(output.exists())

    def test_real_cli_rejects_wrong_leaf_before_signer_or_service(self):
        output = self.root / "real.zip"
        result = REAL_RUN([CLI, *self.arguments(output, ["--expected-leaf-sha256", "0" * 64])],
                          env={**os.environ, **self.environment}, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"MACOS_RELEASE_FAILED\n")
        self.assertEqual(result.stdout, b"")
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
