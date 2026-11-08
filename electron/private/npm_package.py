"""Materialize a declared package with the same normalized manifest it exports."""

import json
from pathlib import Path
import sys

from electron.private.collect_files import collect
from electron.private.identity import package_json


def create_package(source, entries, output, manifest_output, directories_output,
                   dependency_manifests=(), remove_scripts=False):
    original = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(original, dict) or not isinstance(original.get("name"), str) or not original["name"]:
        raise ValueError("Package manifest requires a package name")
    package_json(source, manifest_output, remove_scripts=remove_scripts, dependency_manifests=dependency_manifests)
    directories = collect([*entries, {"source": str(manifest_output), "path": "package.json"}], output)
    Path(directories_output).write_text(json.dumps(directories, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    options = json.loads(Path(sys.argv[1]).read_text())
    create_package(**options, output=sys.argv[2], manifest_output=sys.argv[3], directories_output=sys.argv[4])
