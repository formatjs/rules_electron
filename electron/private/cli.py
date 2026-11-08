import json
import os
from pathlib import Path
import sys
import tempfile

from electron.private.assemble import assemble
from electron.private.archive import create_archive
from electron.private.mac_sign import archive_bundle, sign_bundle


if __name__ == "__main__":
    manifest = json.loads(Path(sys.argv[1]).read_text())
    zip_output = manifest.pop("zip_output", False)
    signing = {name: manifest.pop("macos_" + name, default) for name, default in [
        ("entitlements", ""), ("entitlements_inherit", ""), ("hardened_runtime", False),
    ]}
    if manifest.get("platform") == "macos":
        with tempfile.TemporaryDirectory() as directory:
            unsigned = Path(directory) / "unsigned.app"
            signed = Path(directory) / "signed.app"
            assemble(output=unsigned, **manifest)
            sign_bundle(sys.argv[4], unsigned, signed, **signing)
            archive_bundle(signed, sys.argv[2], manifest["product_name"] + ".app")
            Path(sys.argv[3]).write_text("[]\n")
    elif zip_output:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "app"
            assemble(output=app, **manifest)
            create_archive(app, "linux", "app", "zip", 0, sys.argv[2])
            Path(sys.argv[3]).write_text("[]\n")
    else:
        assemble(output=sys.argv[2], **manifest)
        root = Path(sys.argv[2])
        directories = sorted(Path(path).relative_to(root).as_posix() for path, dirs, files in os.walk(root)
                             if not dirs and not files and Path(path) != root)
        Path(sys.argv[3]).write_text(json.dumps(directories, separators=(",", ":")) + "\n")
