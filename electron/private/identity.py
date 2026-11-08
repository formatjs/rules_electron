"""Explicit app and build versions; never discover identity from the environment."""

import json
from pathlib import Path
import re
import sys

from electron.private.update import _version


def build_identity(version, build_version="", build_number="", platform=""):
    version = _version(version)
    number = r"(?:0|[1-9][0-9]*)"
    if not isinstance(build_number, str) or build_number and not re.fullmatch(number, build_number):
        raise ValueError("build_number must be a nonnegative decimal integer")
    if not isinstance(build_version, str) or build_version and not re.fullmatch(number + r"(?:\." + number + r"){0,3}", build_version):
        raise ValueError("build_version must contain one to four decimal components")
    core = version.split("-", 1)[0].split("+", 1)[0]
    result = build_version or (core + "." + build_number if build_number else version)
    numeric = result.split("-", 1)[0].split("+", 1)[0].split(".")
    if platform == "windows" and any(int(part) > 65535 for part in numeric):
        raise ValueError("Windows build version components must fit 0..65535")
    return result


def package_json(source, output, version="", remove_scripts=False):
    package = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(package, dict):
        raise ValueError("App package manifest must be a JSON object")
    package["version"] = _version(version or package.get("version"))
    if remove_scripts:
        package.pop("scripts", None)
    Path(output).write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    package_json(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1")
