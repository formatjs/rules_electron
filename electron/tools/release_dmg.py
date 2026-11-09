"""Pin signing identity, sign a DMG snapshot, optionally notarize and staple it."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from electron.private.udif import snapshot
from electron.tools.notarize_dmg import notarize
from electron.tools.notarize_macos import backend
from electron.tools.sign_macos import credential, identity, validate_signing


def release(args):
    validate_signing(args)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", args.identifier):
        raise ValueError("Invalid DMG signing identifier")
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
    with tempfile.TemporaryDirectory(prefix=".electron-dmg-release-", dir=output.parent) as temporary:
        root = Path(temporary)
        configuration = root / "empty.toml"
        configuration.write_text("")
        environment = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC", "HOME": str(root),
                       "TMPDIR": str(root), "OPENSSL_CONF": str(configuration)}
        image = root / "release.dmg"
        shutil.copyfile(source, image)
        before = snapshot(image)
        certificates, private = identity(args, crypto, root, environment)
        subprocess.run([signer, "sign", "--config-file", str(configuration), "--pem-file", str(certificates),
                        "--pem-file", str(private), "--signing-time", args.signing_time, "--timestamp-url", args.timestamp_url,
                        "--for-notarization", "--binary-identifier", "@main:" + args.identifier, str(image), str(image)],
                       env=environment, check=True, capture_output=True, timeout=600)
        after = snapshot(image, require_signature=True)
        if before.payload != after.payload:
            raise ValueError("Signing changed DMG payload")
        if args.sign_only:
            image.chmod(0o644)
            os.link(image, output)
        else:
            notarize(argparse.Namespace(input=image, output=output, api_key_env=args.api_key_env,
                                       backend=args.backend, max_wait_seconds=args.max_wait_seconds))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--crypto", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--certificate-env", required=True)
    parser.add_argument("--key-env", required=True)
    parser.add_argument("--password-env")
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--expected-leaf-sha256", required=True)
    parser.add_argument("--expected-team-id", required=True)
    parser.add_argument("--signing-time", required=True)
    parser.add_argument("--timestamp-url", required=True)
    parser.add_argument("--api-key-env")
    parser.add_argument("--sign-only", action="store_true")
    parser.add_argument("--max-wait-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        release(args)
    except Exception:
        print("MACOS_DMG_RELEASE_FAILED", file=sys.stderr)
        return 1
    print("MACOS_DMG_SIGNED" if args.sign_only else "MACOS_DMG_RELEASED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
