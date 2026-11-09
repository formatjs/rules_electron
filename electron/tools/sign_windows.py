"""Explicit release signing with private runtime credentials and leaf pinning."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from python.runfiles import runfiles


def backend():
    files = runfiles.Create()
    repository = files.CurrentRepository() or "_main"
    path = files.Rlocation(repository + "/electron/tools/windows_signing_backend")
    if not path or not Path(path).is_file():
        raise ValueError("Missing declared signer")
    return path


def credential(name):
    path = Path(os.environ[name]).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Credential requires regular file")
    return str(path)


def sign(args):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.expected_leaf_sha256):
        raise ValueError("Expected leaf SHA-256 required")
    if args.signing_time < 0:
        raise ValueError("Invalid signing time")
    source = args.input.resolve(strict=True)
    output = args.output.absolute()
    if not source.is_file() or output.exists() or output.is_symlink():
        raise ValueError("Output must be new file")
    certificate, key = credential(args.certificate_env), credential(args.key_env)
    password = os.environ[args.password_env] if args.password_env else None
    if password is not None and any(c in password for c in "\r\n\0"):
        raise ValueError("Invalid password")
    timestamp = []
    if args.timestamp_url:
        url = urlsplit(args.timestamp_url)
        if (url.scheme != "https" or not url.netloc or url.username is not None
                or url.password is not None or url.query or url.fragment
                or any(ord(c) < 33 for c in args.timestamp_url)
                or not args.tsa_ca_file or not args.https_ca_file):
            raise ValueError("Timestamp requires HTTPS and explicit trust roots")
        timestamp = ["-ts", args.timestamp_url, "-HTTPS-CAfile", str(args.https_ca_file.resolve(strict=True))]
    elif args.tsa_ca_file or args.https_ca_file:
        raise ValueError("Timestamp trust roots require timestamp URL")
    signer = backend()
    with tempfile.TemporaryDirectory(prefix=".electron-sign-", dir=output.parent) as temporary:
        root = Path(temporary)
        empty = root / "openssl.cnf"
        empty.write_text("")
        environment = {"PATH": "", "LC_ALL": "C", "TZ": "UTC", "OPENSSL_CONF": str(empty), "TMPDIR": str(root)}
        unsigned, signed = root / "unsigned", root / "signed"
        shutil.copyfile(source, unsigned)
        command = [signer, "sign", "-certs", certificate, "-key", key, "-h", "sha256",
                   "-time", str(args.signing_time), "-in", str(unsigned), "-out", str(signed)] + timestamp
        if password is not None:
            command += ["-readpass", "-"]
        subprocess.run(command, input=(password + "\n").encode() if password is not None else b"",
                       env=environment, check=True, capture_output=True, timeout=300)
        verify = [signer, "verify", "-CAfile", str(args.ca_file.resolve(strict=True)), "-ignore-cdp",
                  "-require-leaf-hash", "sha256:" + args.expected_leaf_sha256, "-in", str(signed)]
        if args.timestamp_url:
            verify += ["-TSA-CAfile", str(args.tsa_ca_file.resolve(strict=True))]
        result = subprocess.run(verify, env=environment, check=True, capture_output=True, timeout=120)
        if args.timestamp_url and b"Timestamp Server Signature verification: ok" not in result.stdout:
            raise ValueError("Verified timestamp required")
        signed.chmod(source.stat().st_mode & 0o777)
        # Commit only verified bytes; never overwrite a competing release output.
        os.link(signed, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--certificate-env", required=True)
    parser.add_argument("--key-env", required=True)
    parser.add_argument("--password-env")
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--expected-leaf-sha256", required=True)
    parser.add_argument("--signing-time", type=int, required=True)
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--timestamp-url")
    policy.add_argument("--no-timestamp", action="store_true")
    parser.add_argument("--tsa-ca-file", type=Path)
    parser.add_argument("--https-ca-file", type=Path)
    args = parser.parse_args()
    try:
        sign(args)
    except Exception:
        # Backend messages can contain private paths, credentials or service URLs.
        print("WINDOWS_SIGNING_FAILED", file=sys.stderr)
        return 1
    print("WINDOWS_SIGNED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
