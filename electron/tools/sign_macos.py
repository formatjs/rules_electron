"""Pin release identity and sign; optionally stop before notarization and stapling."""

import argparse
import base64
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from electron.private.mac_sign import archive_bundle, signing_arguments
from electron.tools.notarize_macos import backend, extract, notarize


def credential(name):
    path = Path(os.environ[name]).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Credential requires regular file")
    return path


def pem_certificate(der):
    encoded = base64.b64encode(der)
    return (b"-----BEGIN CERTIFICATE-----\n" + b"\n".join(encoded[i:i + 64] for i in range(0, len(encoded), 64))
            + b"\n-----END CERTIFICATE-----\n")


def identity(args, crypto, root, environment):
    certificate, key = credential(args.certificate_env), credential(args.key_env)
    blocks = re.findall(rb"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----",
                        certificate.read_bytes(), re.DOTALL)
    if not blocks:
        raise ValueError("Missing signing certificate")
    decoded = [base64.b64decode(re.sub(rb"\s", b"", block), validate=True) for block in blocks]
    if hashlib.sha256(decoded[0]).hexdigest() != args.expected_leaf_sha256.lower():
        raise ValueError("Unexpected signing certificate")
    certificates = root / "certificates.pem"
    certificates.write_bytes(b"".join(pem_certificate(der) for der in decoded))
    leaf = root / "leaf.pem"
    leaf.write_bytes(pem_certificate(decoded[0]))

    def run(*arguments, **options):
        return subprocess.run([crypto, *map(str, arguments)], env=environment, check=True,
                              capture_output=True, timeout=60, **options).stdout

    subject = run("x509", "-in", leaf, "-noout", "-subject", "-nameopt", "sep_multiline,sname,utf8,esc_ctrl,esc_msb")
    teams = [value.strip() for value in re.findall(rb"^[ \t]*OU[ \t]*=[ \t]*(.*)$", subject, re.MULTILINE)]
    if teams != [args.expected_team_id.encode()]:
        raise ValueError("Unexpected signing team")
    run("verify", "-CAfile", args.ca_file.resolve(strict=True), "-no-CApath", "-no-CAstore",
        "-untrusted", certificates, "-purpose", "any", leaf)
    password = os.environ[args.password_env] if args.password_env else ""
    if any(c in password for c in "\r\n\0"):
        raise ValueError("Invalid key password")
    private = root / "private.pem"
    private_data = run("pkey", "-in", key, "-passin", "stdin", input=(password + "\n").encode())
    with os.fdopen(os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
        output.write(private_data)
    if run("x509", "-in", leaf, "-noout", "-pubkey").strip() != run("pkey", "-in", private, "-pubout").strip():
        raise ValueError("Signing key does not match certificate")
    return certificates, private


def validate_signing(args):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.expected_leaf_sha256):
        raise ValueError("Expected certificate SHA-256")
    if not re.fullmatch(r"[A-Z0-9]{10}", args.expected_team_id):
        raise ValueError("Expected Apple team identifier")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", args.signing_time):
        raise ValueError("Signing time requires explicit UTC")
    datetime.strptime(args.signing_time, "%Y-%m-%dT%H:%M:%SZ")
    timestamp = urlsplit(args.timestamp_url)
    if (timestamp.scheme != "https" or not timestamp.netloc or timestamp.username is not None
            or timestamp.password is not None or timestamp.query or timestamp.fragment
            or any(ord(c) < 33 for c in args.timestamp_url)):
        raise ValueError("Timestamp URL requires HTTPS")
    if not 1 <= args.max_wait_seconds <= 7200:
        raise ValueError("Invalid notarization wait limit")


def release(args):
    validate_signing(args)
    source, output = args.input.resolve(strict=True), args.output.absolute()
    if not source.is_file() or output.exists() or output.is_symlink():
        raise ValueError("Output must be new file")
    if args.sign_only:
        if args.api_key_env:
            raise ValueError("Signing-only client does not accept notary credentials")
    elif not args.api_key_env:
        raise ValueError("Notarization requires API key environment name")
    else:
        credential(args.api_key_env)
    signer, crypto = backend(args.backend), backend(args.crypto)
    with tempfile.TemporaryDirectory(prefix=".electron-macos-release-", dir=output.parent) as temporary:
        root = Path(temporary)
        configuration = root / "empty.conf"
        configuration.write_text("")
        environment = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC", "HOME": str(root),
                       "TMPDIR": str(root), "OPENSSL_CONF": str(configuration)}
        certificates, private = identity(args, crypto, root, environment)
        unsigned = root / "input.zip"
        shutil.copyfile(source, unsigned)
        bundle = extract(unsigned, root)
        settings = signing_arguments(bundle, args.entitlements or "", args.entitlements_inherit or "", True)
        subprocess.run([signer, "sign", "--config-file", str(configuration),
                        "--pem-file", str(certificates), "--pem-file", str(private),
                        "--signing-time", args.signing_time, "--timestamp-url", args.timestamp_url,
                        "--for-notarization", *settings, str(bundle), str(bundle)],
                       env=environment, check=True, capture_output=True, timeout=600)
        signed = root / "signed.zip"
        archive_bundle(bundle, signed, bundle.name)
        if args.sign_only:
            os.link(signed, output)
        else:
            notarize(argparse.Namespace(input=signed, output=output, api_key_env=args.api_key_env,
                                       backend=args.backend, max_wait_seconds=args.max_wait_seconds))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--crypto", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--certificate-env", required=True)
    parser.add_argument("--key-env", required=True)
    parser.add_argument("--password-env")
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--expected-leaf-sha256", required=True)
    parser.add_argument("--expected-team-id", required=True)
    parser.add_argument("--signing-time", required=True)
    parser.add_argument("--timestamp-url", required=True)
    parser.add_argument("--entitlements")
    parser.add_argument("--entitlements-inherit")
    parser.add_argument("--api-key-env")
    parser.add_argument("--sign-only", action="store_true")
    parser.add_argument("--max-wait-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        release(args)
    except Exception:
        print("MACOS_RELEASE_FAILED", file=sys.stderr)
        return 1
    print("MACOS_SIGNED" if args.sign_only else "MACOS_RELEASED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
