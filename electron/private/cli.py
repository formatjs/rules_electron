import json
from pathlib import Path
import sys
import tempfile

from electron.private.assemble import assemble
from electron.private.mac_sign import archive_bundle, sign_bundle


if __name__ == "__main__":
    manifest = json.loads(Path(sys.argv[1]).read_text())
    if manifest.get("platform") == "macos":
        with tempfile.TemporaryDirectory() as directory:
            unsigned = Path(directory) / "unsigned.app"
            signed = Path(directory) / "signed.app"
            assemble(output=unsigned, **manifest)
            sign_bundle(sys.argv[3], unsigned, signed)
            archive_bundle(signed, sys.argv[2], manifest["product_name"] + ".app")
    else:
        assemble(output=sys.argv[2], **manifest)
