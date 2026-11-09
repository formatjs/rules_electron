"""Notarize a signed DMG snapshot; preserve image payload and existing signatures."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from electron.private.udif import snapshot
from electron.tools.notarize_macos import backend


def notarize(args):
    if not 1 <= args.max_wait_seconds <= 7200:
        raise ValueError("Invalid notarization wait limit")
    source, output = args.input.resolve(strict=True), args.output.absolute()
    if not source.is_file() or output.exists() or output.is_symlink():
        raise ValueError("Output must be new file")
    credentials = Path(os.environ[args.api_key_env]).resolve(strict=True)
    if not credentials.is_file():
        raise ValueError("API credential requires regular file")
    signer = backend(args.backend)
    with tempfile.TemporaryDirectory(prefix=".electron-dmg-notary-", dir=output.parent) as temporary:
        root = Path(temporary)
        image = root / "release.dmg"
        shutil.copyfile(source, image)
        before = snapshot(image, require_signature=True)
        configuration = root / "empty.toml"
        configuration.write_text("")
        environment = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC", "HOME": str(root), "TMPDIR": str(root)}
        subprocess.run([signer, "notary-submit", "--config-file", str(configuration), "--api-key-file", str(credentials),
                        "--wait", "--staple", "--max-wait-seconds", str(args.max_wait_seconds), str(image)],
                       env=environment, check=True, capture_output=True, timeout=args.max_wait_seconds + 600)
        after = snapshot(image, require_signature=True, require_ticket=True)
        if after.payload != before.payload or after.signature != before.signature:
            raise ValueError("Notarization changed signed DMG contents")
        image.chmod(0o644)
        os.link(image, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--max-wait-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        notarize(args)
    except Exception:
        print("MACOS_DMG_NOTARIZATION_FAILED", file=sys.stderr)
        return 1
    print("MACOS_DMG_NOTARIZED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
