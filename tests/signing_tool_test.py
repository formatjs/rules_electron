"""Real source-built Authenticode signing, verification and tamper rejection."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SIGNER, OPENSSL, INPUT = [str(Path(value).resolve()) for value in sys.argv[1:4]]


class SigningToolTest(unittest.TestCase):
    def test_pe_sign_verify_reproducibility_and_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {"PATH": "", "HOME": str(root), "LC_ALL": "C.UTF-8", "TZ": "UTC", "OPENSSL_CONF": str(root / "empty.cnf")}
            (root / "empty.cnf").write_text("")
            key, cert = root / "test.key", root / "test.crt"
            # Random test key stays inside this test; no release artifact uses it.
            subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                            "-subj", "/CN=Rules Electron Test Only", "-addext", "extendedKeyUsage=codeSigning",
                            "-addext", "basicConstraints=critical,CA:FALSE",
                            "-addext", "keyUsage=critical,digitalSignature",
                            "-keyout", str(key), "-out", str(cert)], env=environment, check=True, capture_output=True)
            outputs = [root / "first.exe", root / "second.exe"]
            for output in outputs:
                subprocess.run([SIGNER, "sign", "-certs", str(cert), "-key", str(key), "-h", "sha256",
                                "-time", "1700000000", "-in", INPUT, "-out", str(output)],
                               env=environment, check=True, capture_output=True)
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            verify = [SIGNER, "verify", "-CAfile", str(cert), "-ignore-cdp", "-in"]
            result = subprocess.run(verify + [str(outputs[0])], env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace")[-1500:])
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


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
