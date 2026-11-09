"""Real source-built Authenticode signing, verification and tamper rejection."""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile
import zlib

from electron.private.msix import create_msix

SIGNER, OPENSSL, INPUT = [str(Path(value).resolve()) for value in sys.argv[1:4]]


def credentials(root):
    environment = {"PATH": "", "HOME": str(root), "LC_ALL": "C.UTF-8", "TZ": "UTC", "OPENSSL_CONF": str(root / "empty.cnf")}
    (root / "empty.cnf").write_text("")
    key, cert = root / "test.key", root / "test.crt"
    # Random test key stays inside this test; no release artifact uses it.
    subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=Rules Electron Test Only", "-addext", "extendedKeyUsage=codeSigning",
                    "-addext", "basicConstraints=critical,CA:FALSE",
                    "-addext", "keyUsage=critical,digitalSignature",
                    "-keyout", str(key), "-out", str(cert)], env=environment, check=True, capture_output=True)
    return environment, key, cert


class SigningToolTest(unittest.TestCase):
    def test_pe_sign_verify_reproducibility_and_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, key, cert = credentials(root)
            outputs = [root / "first.exe", root / "second.exe"]
            for output in outputs:
                subprocess.run([SIGNER, "sign", "-certs", str(cert), "-key", str(key), "-h", "sha256",
                                "-time", "1700000000", "-in", INPUT, "-out", str(output)],
                               env=environment, check=True, capture_output=True)
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            verify = [SIGNER, "verify", "-CAfile", str(cert), "-ignore-cdp", "-in"]
            result = subprocess.run(verify + [str(outputs[0])], env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace")[-2000:])
            data = bytearray(outputs[0].read_bytes())
            pe = int.from_bytes(data[60:64], "little")
            optional = int.from_bytes(data[pe + 20:pe + 22], "little")
            first_section = pe + 24 + optional
            raw_start = int.from_bytes(data[first_section + 20:first_section + 24], "little")
            self.assertGreater(raw_start, first_section)
            data[raw_start] ^= 1
            changed = root / "changed.exe"
            changed.write_bytes(data)
            rejected = subprocess.run(verify + [str(changed)], env=environment, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b"mismatch", rejected.stdout.lower() + rejected.stderr.lower())
            self.assertIn(b"osslsigncode 2.15", subprocess.check_output([SIGNER, "--version"], env=environment))

    def test_msix_sign_verify_preserves_payload_and_adds_signature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, key, cert = credentials(root)
            app = root / "app"
            app.mkdir()
            (app / "sample.exe").write_bytes(Path(INPUT).read_bytes())
            (app / "payload.bin").write_bytes(bytes(range(256)) * 1024)
            package = root / "package.json"
            package.write_text('{"version":"1.0.0"}')
            logos = []
            for size in (44, 150, 50):
                def chunk(kind, data):
                    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
                image = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff" * size * 4) * size)) + chunk(b"IEND", b""))
                logo = root / (str(size) + ".png")
                logo.write_bytes(image)
                logos.append(logo)
            source = root / "unsigned.msix"
            create_msix(app, package, source, "org.example.Signing", "CN=Rules Electron Test Only",
                        "Example", "Signing Probe", "sample", "x64", *logos)
            with ZipFile(source) as archive:
                original = {name: archive.read(name) for name in archive.namelist() if name != "[Content_Types].xml"}
            signed = root / "signed.msix"
            subprocess.run([SIGNER, "sign", "-certs", str(cert), "-key", str(key), "-h", "sha256",
                            "-time", "1700000000", "-in", str(source), "-out", str(signed)],
                           env=environment, check=True, capture_output=True)
            result = subprocess.run([SIGNER, "verify", "-CAfile", str(cert), "-ignore-cdp", "-in", str(signed)],
                                    env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace")[-2000:])
            with ZipFile(signed) as archive:
                self.assertEqual(archive.namelist()[-1], "AppxSignature.p7x")
                self.assertEqual(archive.read("AppxSignature.p7x")[:4], b"PKCX")
                self.assertIn(b"application/vnd.ms-appx.signature", archive.read("[Content_Types].xml"))
                self.assertEqual({name: archive.read(name) for name in original}, original)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
