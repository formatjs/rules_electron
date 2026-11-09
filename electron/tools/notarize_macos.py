"""Notarize a signed app snapshot; commit only the stapled release ZIP."""

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from python.runfiles import runfiles

from electron.private.archive import inventory
from electron.private.mac_sign import archive_bundle

TICKET = "Contents/CodeResources"


def backend(key):
    logical = PurePosixPath(key)
    if (not logical.parts or logical.is_absolute() or key != logical.as_posix()
            or ".." in logical.parts or any(c in key for c in ("\\", ":", "\0"))):
        raise ValueError("Expected declared backend runfile")
    path = runfiles.Create().Rlocation(key)
    if not path or not Path(path).is_file():
        raise ValueError("Missing declared notarization backend")
    return path


def snapshot(bundle):
    result = {}
    with inventory(bundle, "macos") as (entries, open_entry):
        for name, entry in entries.items():
            if name == TICKET:
                continue
            value = entry.target
            if entry.kind == "file":
                digest = hashlib.sha256()
                with open_entry(entry) as content:
                    for block in iter(lambda: content.read(1024 * 1024), b""):
                        digest.update(block)
                value = (entry.size, digest.hexdigest())
            result[name] = (entry.kind, stat.S_IMODE((bundle / name).lstat().st_mode), value)
    return result


def extract(source, directory):
    with ZipFile(source) as archive:
        roots = {entry.filename.split("/", 1)[0] for entry in archive.infolist()}
    if len(roots) != 1:
        raise ValueError("Expected one app bundle")
    bundle = directory / next(iter(roots))
    with inventory(source, "macos") as (entries, open_entry):
        if len(entries) > 200000 or sum(entry.size for entry in entries.values()) > 16 * 1024**3:
            raise ValueError("App snapshot exceeds limits")
        bundle.mkdir()
        for name, entry in sorted(entries.items()):
            if entry.kind == "symlink":
                continue
            path = bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.kind == "directory":
                path.mkdir(exist_ok=True)
            else:
                with open_entry(entry) as content, path.open("wb") as output:
                    shutil.copyfileobj(content, output)
            path.chmod(entry.mode)
        for name, entry in sorted(entries.items()):
            if entry.kind == "symlink":
                path = bundle / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(entry.target)
    contents = bundle / "Contents"
    if contents.is_symlink() or not contents.is_dir():
        raise ValueError("Expected app Contents directory")
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    if info.get("CFBundlePackageType") != "APPL":
        raise ValueError("Expected application bundle")
    ticket = bundle / TICKET
    if ticket.is_symlink() or (ticket.exists() and not ticket.is_file()):
        raise ValueError("Invalid existing ticket")
    if ticket.exists():
        ticket.unlink()
    return bundle


def notarize(args):
    if not 1 <= args.max_wait_seconds <= 7200:
        raise ValueError("Invalid notarization wait limit")
    source = args.input.resolve(strict=True)
    output = args.output.absolute()
    if not source.is_file() or output.exists() or output.is_symlink():
        raise ValueError("Output must be new file")
    credentials = Path(os.environ[args.api_key_env]).resolve(strict=True)
    if not credentials.is_file():
        raise ValueError("API credential requires regular file")
    signer = backend(args.backend)
    with tempfile.TemporaryDirectory(prefix=".electron-notarize-", dir=output.parent) as temporary:
        root = Path(temporary)
        unsigned = root / "input.zip"
        shutil.copyfile(source, unsigned)
        bundle = extract(unsigned, root)
        before = snapshot(bundle)
        configuration = root / "rcodesign.toml"
        configuration.write_text("")
        environment = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC", "HOME": str(root), "TMPDIR": str(root)}
        subprocess.run([signer, "notary-submit", "--config-file", str(configuration),
                        "--api-key-file", str(credentials), "--wait", "--staple",
                        "--max-wait-seconds", str(args.max_wait_seconds), str(bundle)],
                       check=True, capture_output=True, timeout=args.max_wait_seconds + 600, env=environment)
        ticket = bundle / TICKET
        if ticket.is_symlink() or not ticket.is_file() or not ticket.stat().st_size:
            raise ValueError("Missing notarization ticket")
        if snapshot(bundle) != before:
            raise ValueError("Notarization changed signed app contents")
        ticket.chmod(0o644)
        signed = root / "notarized.zip"
        archive_bundle(bundle, signed, bundle.name)
        os.link(signed, output)


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
        print("MACOS_NOTARIZATION_FAILED", file=sys.stderr)
        return 1
    print("MACOS_NOTARIZED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
