"""Invoke public release signing with real source-built tools and private test keys."""

import base64
import hashlib
import os
from pathlib import Path
import ssl
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from electron.private.msix import create_msix
from electron.private.update import create_feed

CLI, OPENSSL, INPUT = [str(Path(value).resolve()) for value in sys.argv[1:4]]


class SignWindowsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.key, self.certificate = self.root / "private.key", self.root / "certificate.pem"
        config = self.root / "empty.cnf"
        config.write_text("")
        self.clean = {"PATH": "", "OPENSSL_CONF": str(config), "LC_ALL": "C", "TZ": "UTC"}
        subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-days", "1",
                        "-subj", "/CN=Release Interface Test", "-addext", "extendedKeyUsage=codeSigning",
                        "-addext", "basicConstraints=critical,CA:FALSE", "-addext", "keyUsage=critical,digitalSignature",
                        "-passout", "stdin", "-keyout", str(self.key), "-out", str(self.certificate)],
                       input=b"fixture-private-password\n", env=self.clean, check=True, capture_output=True)
        self.fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.certificate.read_text())).hexdigest()
        self.environment = {**os.environ, "RELEASE_CERT": str(self.certificate),
                            "RELEASE_KEY": str(self.key), "RELEASE_PASSWORD": "fixture-private-password"}

    def sign(self, source, name, success=True, extra=(), environment=None):
        output = self.root / name
        command = [CLI, "--input", str(source), "--output", str(output),
                   "--certificate-env", "RELEASE_CERT", "--key-env", "RELEASE_KEY",
                   "--password-env", "RELEASE_PASSWORD", "--ca-file", str(self.certificate),
                   "--expected-leaf-sha256", self.fingerprint, "--signing-time", "1700000000",
                   "--no-timestamp", *extra]
        result = subprocess.run(command, env=environment or self.environment, capture_output=True, timeout=60)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        self.assertEqual(result.stdout if success else result.stderr,
                         b"WINDOWS_SIGNED\n" if success else b"WINDOWS_SIGNING_FAILED\n")
        for secret in (b"fixture-private-password", str(self.key).encode()):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return output

    def test_encrypted_key_repeatability_and_final_feed_hash(self):
        first = self.sign(INPUT, "signed.exe")
        second = self.sign(INPUT, "repeat.exe")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertNotEqual(first.read_bytes(), Path(INPUT).read_bytes())
        package = self.root / "package.json"
        package.write_text('{"version":"2.0.0"}')
        feed = create_feed(artifacts=[{"source": first, "name": "Sample-2.0.0.exe"}],
                           package_json=package, output=self.root / "feed", platform="windows",
                           architecture="x64", release_date="2026-01-02T03:04:05Z")
        self.assertEqual(feed["files"][0]["sha512"],
                         base64.b64encode(hashlib.sha512(first.read_bytes()).digest()).decode())
        self.assertEqual(feed["files"][0]["size"], first.stat().st_size)

    def test_wrong_identity_or_password_never_emits_output(self):
        for name, extra, environment in [
            ("wrong-pin.exe", ["--expected-leaf-sha256", "0" * 64], self.environment),
            ("wrong-password.exe", [], {**self.environment, "RELEASE_PASSWORD": "wrong"}),
        ]:
            with self.subTest(name=name):
                output = self.sign(INPUT, name, False, extra, environment)
                self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".electron-sign-*")))

    def test_existing_release_is_preserved(self):
        output = self.root / "existing.exe"
        output.write_bytes(b"existing release")
        self.sign(INPUT, output.name, False)
        self.assertEqual(output.read_bytes(), b"existing release")

    def test_untrusted_certificate_rejected(self):
        empty = self.root / "untrusted.pem"
        empty.write_text("")
        output = self.sign(INPUT, "untrusted.exe", False, ["--ca-file", str(empty)])
        self.assertFalse(output.exists())

    def test_msix_signature_uses_same_verified_interface(self):
        app = self.root / "app"
        app.mkdir()
        (app / "sample.exe").write_bytes(Path(INPUT).read_bytes())
        package = self.root / "package.json"
        package.write_text('{"version":"2.0.0"}')
        logos = []
        for size in (44, 150, 50):
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
            data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff" * size * 4) * size)) + chunk(b"IEND", b""))
            logo = self.root / (str(size) + ".png")
            logo.write_bytes(data)
            logos.append(logo)
        source = self.root / "unsigned.msix"
        create_msix(app, package, source, "org.example.ReleaseSigning", "CN=Release Interface Test",
                    "Example", "Signing Probe", "sample", "x64", *logos)
        output = self.sign(source, "signed.msix")
        self.assertGreater(output.stat().st_size, source.stat().st_size)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
