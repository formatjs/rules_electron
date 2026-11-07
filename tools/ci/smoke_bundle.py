import json
from pathlib import Path
import shutil
import stat
import sys
import struct
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

from tools.ci.smoke_shards import ALL_VARIANTS, SHARDS


def check_binary(source, target_os, arm64):
    header = source.read(64)
    if target_os == "linux":
        valid = header[:4] == b"\x7fELF" and struct.unpack_from("<H", header, 18)[0] == (183 if arm64 else 62)
    elif target_os == "macos":
        valid = header[:4] == b"\xcf\xfa\xed\xfe" and struct.unpack_from("<I", header, 4)[0] == 0x0100000C
    else:
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset > 1024**2:
            raise ValueError("Invalid PE header offset")
        source.seek(offset)
        pe = source.read(6)
        valid = header[:2] == b"MZ" and pe[:4] == b"PE\0\0" and struct.unpack_from("<H", pe, 4)[0] == (0xAA64 if arm64 else 0x8664)
    if not valid:
        raise ValueError("App, addon or helper has wrong binary architecture")


def check_app(entry):
    variant = entry["variant"]
    target_os = variant.split("_")[0]
    arm64 = "aarch64" in variant
    prefix = "Contents/Resources/" if target_os == "macos" else "resources/"
    binary = "Contents/MacOS/sample-desktop" if target_os == "macos" else "sample-desktop" + (".exe" if target_os == "windows" else "")
    paths = [binary, prefix + "native/helper" + (".exe" if target_os == "windows" else ""), prefix + "app.asar.unpacked/node_modules/example-native/addon.node"]
    if entry["directory"]:
        for name in paths:
            with (Path(entry["source"]) / name).open("rb") as source:
                check_binary(source, target_os, arm64)
    else:
        with ZipFile(entry["source"]) as archive:
            for name in paths:
                with archive.open("Sample Desktop.app/" + name) as source:
                    check_binary(source, target_os, arm64)


def build_bundles(entries, outputs):
    apps = [entry for entry in entries if not entry.get("package")]
    if len(apps) != len(ALL_VARIANTS) or {entry["variant"] for entry in apps} != ALL_VARIANTS:
        raise ValueError("Expected exactly seven cross-built app variants")
    if set(outputs) != set(SHARDS) or any(entry["variant"] not in ALL_VARIANTS for entry in entries):
        raise ValueError("Unexpected smoke output or variant")
    for entry in apps:
        check_app(entry)
    for shard, variants in SHARDS.items():
        with ZipFile(outputs[shard], "w", compression=ZIP_DEFLATED, compresslevel=1) as archive:
            names = set()
            for entry in sorted(entries, key=lambda e: (e["variant"], e["source"])):
                if entry["variant"] in variants:
                    add_entry(archive, entry, names)


def add_entry(archive, entry, names):
    source = Path(entry["source"])
    files = sorted(source.rglob("*")) if entry["directory"] else [source]
    for file in files:
        if file.is_symlink():
            raise ValueError("Smoke tree inputs must not contain symlinks")
        if file.is_dir():
            continue
        if not stat.S_ISREG(file.stat().st_mode):
            raise ValueError("Smoke inputs must be regular files")
        if entry.get("package"):
            name = entry["variant"] + "/packages/" + source.name + ("/" + file.relative_to(source).as_posix() if entry["directory"] else "")
        else:
            name = entry["variant"] + "/" + ("app/" + file.relative_to(source).as_posix() if entry["directory"] else "app.zip")
        if name in names:
            raise ValueError(f"Duplicate smoke member: {name}")
        names.add(name)
        info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = file.stat().st_mode << 16
        info.compress_type = ZIP_STORED if entry.get("package") and file.suffix in (".deb", ".exe") else ZIP_DEFLATED
        # Python 3.11 ZipFile.open uses ZipInfo's level, not the archive's.
        info._compresslevel = 1
        with file.open("rb") as content, archive.open(info, "w", force_zip64=True) as destination:
                shutil.copyfileobj(content, destination)


if __name__ == "__main__":
    build_bundles(**json.loads(Path(sys.argv[1]).read_text()))
