"""Sign an app snapshot, package its DMG, then sign and optionally notarize it."""

import argparse
from pathlib import Path
import plistlib
import sys
import tempfile

from electron.private.dmg import create_dmg
from electron.tools import release_dmg, sign_macos
from electron.tools.notarize_macos import backend, extract


def distribute(args):
    sign_macos.validate_signing(args)
    source, output = args.input.resolve(strict=True), args.output.absolute()
    if not source.is_file() or output.exists() or output.is_symlink():
        raise ValueError("Output must be new file")
    if not args.sign_only:
        if not args.api_key_env:
            raise ValueError("Notarization requires API key environment name")
        sign_macos.credential(args.api_key_env)
    elif args.api_key_env:
        raise ValueError("Signing-only client does not accept notary credentials")
    with tempfile.TemporaryDirectory(prefix=".electron-distribution-", dir=output.parent) as directory:
        root = Path(directory)
        signed = root / "signed.zip"
        sign_macos.release(argparse.Namespace(**dict(vars(args), input=source, output=signed,
                                                    sign_only=True, api_key_env=None)))
        bundle = extract(signed, root)
        info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
        identifier = info.get("CFBundleIdentifier", "")
        if args.identifier and args.identifier != identifier:
            raise ValueError("DMG identity differs from signed app")
        image = root / "unsigned.dmg"
        icon_name = info.get("CFBundleIconFile", "")
        icon = bundle / "Contents/Resources" / icon_name if icon_name else None
        if icon_name and (Path(icon_name).name != icon_name or not icon.is_file()):
            raise ValueError("Invalid app icon reference")
        create_dmg(bundle, bundle.name, args.volume_name or bundle.stem, args.source_date_epoch,
                   True, backend(args.xorriso), backend(args.converter), image,
                   finder_window=(100, 100, 640, 400), icon_size=80,
                   volume_icon=str(icon) if icon else "")
        release_dmg.release(argparse.Namespace(**dict(vars(args), input=image, output=output,
                                                     identifier=identifier)))


def main(argv=None):
    parser = sign_macos.argument_parser(__doc__)
    parser.add_argument("--xorriso", required=True)
    parser.add_argument("--converter", required=True)
    parser.add_argument("--volume-name", default="")
    parser.add_argument("--identifier", default="")
    parser.add_argument("--source-date-epoch", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        sign_macos.resolve_runfiles(args)
        distribute(args)
    except Exception:
        print("MACOS_DISTRIBUTION_FAILED", file=sys.stderr)
        return 1
    print("MACOS_DISTRIBUTION_SIGNED" if args.sign_only else "MACOS_DISTRIBUTION_RELEASED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
