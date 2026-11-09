"""Invoke public release signing with real source-built tools and private test keys."""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
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

    def sign(self, source, name, success=True, extra=(), environment=None, timestamp=None):
        output = self.root / name
        command = [CLI, "--input", str(source), "--output", str(output),
                   "--certificate-env", "RELEASE_CERT", "--key-env", "RELEASE_KEY",
                   "--password-env", "RELEASE_PASSWORD", "--ca-file", str(self.certificate),
                   "--expected-leaf-sha256", self.fingerprint, "--signing-time", "1700000000",
                   *(timestamp or ["--no-timestamp"]), *extra]
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

    def test_real_rfc3161_over_https_and_timestamp_failure(self):
        def openssl(*args):
            return subprocess.run([OPENSSL, *map(str, args)], env=self.clean,
                                  check=True, capture_output=True, timeout=30)

        root_cert, root_key = self.root / "root.pem", self.root / "root.key"
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", "/CN=Local Timestamp Test Root", "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-keyout", root_key, "-out", root_cert)
        certificates = {}
        for name, extensions in [
            ("tsa", "extendedKeyUsage=critical,timeStamping\n"),
            ("server", "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n"),
        ]:
            key, cert, csr = [self.root / (name + suffix) for suffix in (".key", ".pem", ".csr")]
            extension_file = self.root / (name + ".ext")
            extension_file.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n" + extensions)
            openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=Local " + name,
                    "-keyout", key, "-out", csr)
            openssl("x509", "-req", "-in", csr, "-CA", root_cert, "-CAkey", root_key,
                    "-set_serial", "10" if name == "tsa" else "11", "-days", "1", "-extfile", extension_file, "-out", cert)
            certificates[name] = (key, cert)
        serial = self.root / "tsa.serial"
        serial.write_text("01\n")
        config = self.root / "tsa.cnf"
        config.write_text(
            "[tsa]\ndefault_tsa=local\n[local]\n"
            + f"serial={serial}\nsigner_cert={certificates['tsa'][1]}\nsigner_key={certificates['tsa'][0]}\ncerts={root_cert}\n"
            + "signer_digest=sha256\ndefault_policy=1.2.3.4.1\ndigests=sha256\naccuracy=secs:1\n"
            + "ordering=yes\ntsa_name=yes\ness_cert_id_chain=no\ness_cert_id_alg=sha256\n"
        )
        requests, fail = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length < 1024 * 1024:
                    self.send_error(400)
                    return
                requests.append(self.headers.get("Content-Type"))
                query = owner.root / "request.tsq"
                query.write_bytes(self.rfile.read(length))
                reply = owner.root / "reply.tsr"
                if fail:
                    self.send_error(503)
                    return
                openssl("ts", "-reply", "-config", config, "-queryfile", query, "-out", reply)
                data = reply.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/timestamp-reply")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(str(certificates["server"][1]), str(certificates["server"][0]))
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        timestamp = ["--timestamp-url", "https://127.0.0.1:" + str(server.server_port) + "/",
                     "--https-ca-file", str(root_cert), "--tsa-ca-file", str(root_cert)]
        signed = self.sign(INPUT, "timestamped.exe", timestamp=timestamp)
        self.assertTrue(signed.is_file())
        self.assertEqual(requests, ["application/timestamp-query"])
        empty_roots = self.root / "empty-roots.pem"
        empty_roots.write_text("")
        rejected = self.sign(INPUT, "bad-transport-roots.exe", False,
                             ["--https-ca-file", str(empty_roots)], timestamp=timestamp)
        self.assertFalse(rejected.exists())
        self.assertEqual(len(requests), 1)
        wrong_extensions = self.root / "wrong-host.ext"
        wrong_extensions.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
                                    "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.2\n")
        wrong_host = self.root / "wrong-host.pem"
        openssl("x509", "-req", "-in", self.root / "server.csr", "-CA", root_cert, "-CAkey", root_key,
                "-set_serial", "12", "-days", "1", "-extfile", wrong_extensions, "-out", wrong_host)
        tls.load_cert_chain(str(wrong_host), str(certificates["server"][0]))
        rejected = self.sign(INPUT, "wrong-host.exe", False, timestamp=timestamp)
        self.assertFalse(rejected.exists())
        self.assertEqual(len(requests), 1)
        tls.load_cert_chain(str(certificates["server"][1]), str(certificates["server"][0]))
        rejected = self.sign(INPUT, "untrusted-tsa.exe", False,
                             ["--tsa-ca-file", str(self.certificate)], timestamp=timestamp)
        self.assertFalse(rejected.exists())
        self.assertEqual(len(requests), 2)
        fail.append(True)
        rejected = self.sign(INPUT, "failed-timestamp.exe", False, timestamp=timestamp)
        self.assertFalse(rejected.exists())
        self.assertEqual(len(requests), 3)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
