"""Real identity preflight and signer layouts with simulated Apple service replies."""

from contextlib import redirect_stderr, redirect_stdout
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

from electron.private.dmg import create_dmg
from electron.private.udif import CMS, CODE_DIRECTORY, TICKET, snapshot
from electron.tools import notarize_dmg, release_dmg

CLI = str(Path(sys.argv.pop(1)).resolve())
SIGNER_KEY, CRYPTO_KEY = sys.argv[1:3]
del sys.argv[1:3]
XORRISO, CONVERTER = [str(Path(value).resolve()) for value in sys.argv[1:3]]
del sys.argv[1:3]
SIGNER, CRYPTO = release_dmg.backend(SIGNER_KEY), release_dmg.backend(CRYPTO_KEY)
REAL_RUN = subprocess.run


def wrapper(data):
    return struct.pack(">II", 0xfade0b01, len(data) + 8) + data


def replace_blobs(path, blobs):
    data = path.read_bytes()
    image = snapshot(path)
    entries = sorted(blobs.items())
    offset = 12 + len(entries) * 8
    indices, content = [], []
    for slot, blob in entries:
        indices.append(struct.pack(">II", slot, offset))
        content.append(blob)
        offset += len(blob)
    signature = struct.pack(">III", 0xfade0cc0, offset, len(entries)) + b"".join(indices + content)
    trailer = bytearray(data[-512:])
    struct.pack_into(">QQ", trailer, 296, image.payload[0], len(signature))
    path.write_bytes(data[:image.payload[0]] + signature + trailer)


class DmgReleaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.empty = self.root / "empty.cnf"
        self.empty.write_text("")
        self.clean = {"PATH": "", "HOME": str(self.root), "OPENSSL_CONF": str(self.empty), "LC_ALL": "C", "TZ": "UTC"}
        self.cert, self.key = self.root / "certificate.pem", self.root / "private.key"
        REAL_RUN([CRYPTO, "req", "-x509", "-newkey", "rsa:2048", "-days", "1", "-subj", "/CN=DMG Test/OU=TEAMROOT12",
                  "-addext", "extendedKeyUsage=codeSigning", "-addext", "basicConstraints=critical,CA:FALSE",
                  "-passout", "stdin", "-keyout", str(self.key), "-out", str(self.cert)],
                 env=self.clean, input=b"never-log-password\n", check=True, capture_output=True, timeout=30)
        self.pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.cert.read_text())).hexdigest()
        api = self.root / "api.json"
        api.write_text('{"fixture":"never-log-password"}')
        self.environment = {"DMG_CERT": str(self.cert), "DMG_KEY": str(self.key),
                            "DMG_PASSWORD": "never-log-password", "DMG_API": str(api)}
        bundle = self.root / "Sample.app"
        (bundle / "Contents/MacOS").mkdir(parents=True)
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundlePackageType": "APPL", "CFBundleExecutable": "sample"}))
        main = bundle / "Contents/MacOS/sample"
        main.write_bytes(b"immutable executable fixture")
        main.chmod(0o755)
        self.source = self.root / "input.dmg"
        create_dmg(bundle, "Sample.app", "Sample", 0, True, XORRISO, CONVERTER, self.source)
        self.original = self.source.read_bytes()
        self.calls = []

    def arguments(self, output, extra=(), sign_only=False):
        return ["--backend", SIGNER_KEY, "--crypto", CRYPTO_KEY, "--input", str(self.source), "--output", str(output),
                "--identifier", "org.example.release", "--certificate-env", "DMG_CERT", "--key-env", "DMG_KEY", "--password-env", "DMG_PASSWORD",
                "--ca-file", str(self.cert), "--expected-leaf-sha256", self.pin, "--expected-team-id", "TEAMROOT12",
                "--signing-time", "2026-11-09T01:02:03Z", "--timestamp-url", "https://timestamp.example.com/",
                *(["--sign-only"] if sign_only else ["--api-key-env", "DMG_API"]), *extra]

    def service(self, command, **options):
        if command[0] != SIGNER:
            return REAL_RUN(command, **options)
        self.calls.append(command[1])
        self.assertEqual(options["env"]["PATH"], "")
        self.assertNotIn("DMG_PASSWORD", options["env"])
        self.assertNotIn("DMG_API", options["env"])
        image = Path(command[-1])
        if command[1] == "sign":
            self.assertIn("--for-notarization", command)
            self.assertEqual(command[command.index("--binary-identifier") + 1], "@main:org.example.release")
            self.assertEqual(command[command.index("--timestamp-url") + 1], "https://timestamp.example.com/")
            private = Path(command[command.index("--pem-file", command.index("--pem-file") + 1) + 1])
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
            REAL_RUN([SIGNER, "sign", "--config-file", str(self.empty), "--timestamp-url", "none",
                      "--binary-identifier", "@main:org.example.release", str(image), str(image)],
                     env=options["env"], capture_output=True, check=True, timeout=60)
            blobs = snapshot(image).blobs
            directory = bytearray(blobs[CODE_DIRECTORY])
            struct.pack_into(">I", directory, 12, struct.unpack_from(">I", directory, 12)[0] & ~2)
            blobs[CODE_DIRECTORY] = bytes(directory)
            blobs[CMS] = wrapper(b"simulated certificate signature")
            replace_blobs(image, blobs)
        elif command[1] == "notary-submit":
            self.assertIn("--wait", command)
            self.assertIn("--staple", command)
            blobs = snapshot(image, require_signature=True).blobs
            blobs[TICKET] = wrapper(b"simulated accepted Apple ticket")
            replace_blobs(image, blobs)
        else:
            self.fail("Unexpected service operation")

    def invoke(self, name="release.dmg", extra=(), sign_only=False, effect=None, success=True):
        output = self.root / name
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.environment), patch.object(release_dmg.subprocess, "run", side_effect=effect or self.service), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status = release_dmg.main(self.arguments(output, extra, sign_only))
        self.assertEqual(status, 0 if success else 1)
        self.assertEqual(stdout.getvalue(), ("MACOS_DMG_SIGNED\n" if sign_only else "MACOS_DMG_RELEASED\n") if success else "")
        self.assertEqual(stderr.getvalue(), "" if success else "MACOS_DMG_RELEASE_FAILED\n")
        self.assertNotIn("never-log-password", stdout.getvalue() + stderr.getvalue())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob(".electron-dmg-*")))
        return output

    def test_release_signs_then_staples_without_changing_image_payload(self):
        output = self.invoke()
        self.assertEqual(self.calls, ["sign", "notary-submit"])
        self.assertEqual(snapshot(output, require_signature=True, require_ticket=True).payload, snapshot(self.source).payload)

    def test_sign_only_skips_notary_service(self):
        output = self.invoke(sign_only=True)
        self.assertEqual(self.calls, ["sign"])
        self.assertNotIn(TICKET, snapshot(output, require_signature=True).blobs)

    def test_identity_and_timestamp_fail_before_signer(self):
        for index, extra in enumerate([["--expected-leaf-sha256", "0" * 64], ["--expected-team-id", "OTHERTEAM1"],
                                       ["--timestamp-url", "http://timestamp.example.com/"], ["--identifier", "bad:identifier"]]):
            output = self.invoke(str(index) + ".dmg", extra, success=False)
            self.assertFalse(output.exists())
            self.assertEqual(self.calls, [])

    def test_failures_and_changes_to_payload_or_signature_never_commit(self):
        for index, mutation in enumerate(("reject", "payload", "signature", "ticket")):
            self.calls.clear()
            def changed(command, **options):
                if command[0] == SIGNER and command[1] == "notary-submit" and mutation == "reject":
                    raise subprocess.CalledProcessError(1, command, stderr=b"never-log-password")
                result = self.service(command, **options)
                if command[0] == SIGNER and command[1] == "notary-submit":
                    image = Path(command[-1])
                    if mutation == "payload":
                        data = bytearray(image.read_bytes())
                        data[0] ^= 1
                        image.write_bytes(data)
                    else:
                        blobs = snapshot(image).blobs
                        if mutation == "signature":
                            blobs[CMS] = wrapper(b"different certificate signature")
                        elif mutation == "ticket":
                            del blobs[TICKET]
                        replace_blobs(image, blobs)
                return result
            output = self.invoke(str(index) + ".dmg", effect=changed, success=False)
            self.assertFalse(output.exists())

    def test_output_race_preserves_competing_file(self):
        output = self.root / "race.dmg"
        def competing(command, **options):
            result = self.service(command, **options)
            if command[0] == SIGNER and command[1] == "notary-submit":
                output.write_bytes(b"competing output")
            return result
        self.invoke(output.name, effect=competing, success=False)
        self.assertEqual(output.read_bytes(), b"competing output")

    def test_signing_payload_change_stops_before_notary(self):
        def changed(command, **options):
            result = self.service(command, **options)
            if command[0] == SIGNER and command[1] == "sign":
                image = Path(command[-1])
                data = bytearray(image.read_bytes())
                data[0] ^= 1
                image.write_bytes(data)
            return result
        output = self.invoke(effect=changed, success=False)
        self.assertEqual(self.calls, ["sign"])
        self.assertFalse(output.exists())

    def test_standalone_notarization_and_real_cli_preflight(self):
        signed = self.invoke(sign_only=True)
        output = self.root / "standalone.dmg"
        with patch.dict(os.environ, self.environment), patch.object(notarize_dmg.subprocess, "run", side_effect=self.service), \
                redirect_stdout(io.StringIO()):
            status = notarize_dmg.main(["--backend", SIGNER_KEY, "--input", str(signed), "--output", str(output), "--api-key-env", "DMG_API"])
        self.assertEqual(status, 0)
        self.assertIn(TICKET, snapshot(output, require_signature=True, require_ticket=True).blobs)
        rejected = self.root / "rejected.dmg"
        result = REAL_RUN([CLI, *self.arguments(rejected, ["--expected-leaf-sha256", "0" * 64])],
                          env={**os.environ, **self.environment}, capture_output=True, timeout=60)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", b"MACOS_DMG_RELEASE_FAILED\n"))
        self.assertFalse(rejected.exists())


if __name__ == "__main__":
    unittest.main()
