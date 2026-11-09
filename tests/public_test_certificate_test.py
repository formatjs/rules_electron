"""Fixed public test certificate: reproducibility, identity and signing purpose."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

WRITER, KEY, OPENSSL = [str(Path(value).resolve()) for value in sys.argv[1:4]]


class PublicCertificateTest(unittest.TestCase):
    def test_fixed_certificate_across_paths_and_native_openssl_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {"PATH": "", "LC_ALL": "C", "TZ": "UTC", "OPENSSL_CONF": str(root / "empty.cnf")}
            (root / "empty.cnf").write_text("")
            writer_environment = dict(environment, OPENSSL_CONF=str(root / "missing.cnf"))
            results = []
            for name in ("first", "other path"):
                destination = root / name
                destination.mkdir()
                pem, der = destination / "fixture.pem", destination / "fixture.cer"
                result = subprocess.run([WRITER, KEY, str(pem), str(der)], env=writer_environment, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace")[-1200:])
                results.append((pem.read_bytes(), der.read_bytes()))
            self.assertEqual(results[0], results[1])
            pem = root / "first/fixture.pem"
            text = subprocess.check_output([OPENSSL, "x509", "-in", str(pem), "-noout", "-subject", "-issuer",
                                            "-dates", "-ext", "keyUsage,extendedKeyUsage,basicConstraints"], env=environment).decode()
            self.assertIn("subject=CN=Example", text.replace(" = ", "="))
            self.assertIn("issuer=CN=Example", text.replace(" = ", "="))
            self.assertIn("2036 GMT", text)
            self.assertIn("Digital Signature", text)
            self.assertIn("Code Signing", text)
            self.assertIn("CA:FALSE", text)
            subprocess.run([OPENSSL, "verify", "-CAfile", str(pem), "-attime", "1767225600", str(pem)],
                           env=environment, check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
