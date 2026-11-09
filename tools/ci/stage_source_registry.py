"""Stage the pinned Electron module registry for a source-runtime consumer."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from python.runfiles import runfiles


def source_inputs():
    files = runfiles.Create()
    anchor = files.Rlocation("electron_source_overlay/registry_build_files.json")
    repository = files.CurrentRepository() or "_main"
    pin = files.Rlocation(repository + "/tools/ci/electron_source_pin.json")
    if not anchor or not pin:
        raise ValueError("Missing declared Electron registry inputs")
    return Path(anchor).parent, json.loads(Path(pin).read_text())


def restore_build_files(root, manifest):
    for name, contents in manifest.items():
        parts = name.split("/")
        if (parts[0] != "bcr" or parts[-1] not in ("BUILD", "BUILD.bazel")
                or any(part in ("", ".", "..") for part in parts) or "\\" in name):
            raise ValueError("Invalid registry BUILD input")
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


def stage_registry(output):
    source, pin = source_inputs()
    with tempfile.TemporaryDirectory(prefix="electron-registry-inputs-") as temporary:
        root = Path(temporary)
        shutil.copytree(source / "bcr", root / "bcr")
        restore_build_files(root, json.loads((source / "registry_build_files.json").read_text()))
        subprocess.run([sys.executable, str(source / "registry_stage_script"),
                        "--source-registry", str(root / "bcr"), "--target-registry", str(output),
                        "--module", "electron", "--version", pin["version"]],
                       check=True, capture_output=True)
    return output / "modules/electron" / pin["version"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        stage_registry(args.output.absolute())
    except Exception:
        print("SOURCE_REGISTRY_STAGE_FAILED", file=sys.stderr)
        return 1
    print("SOURCE_REGISTRY_STAGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
