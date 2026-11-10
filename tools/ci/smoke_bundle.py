import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import struct
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

from tools.ci.smoke_shards import ALL_VARIANTS, SHARDS

VALIDATED = b"SMOKE_APPS_VALIDATED\n"


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
    paths = [binary, prefix + "native/helper" + (".exe" if target_os == "windows" else "")]
    paths += [prefix + "app.asar.unpacked/node_modules/example-native/" + name
              for name in ("addon.node", "classic.node", "bad-abi.node")]
    if target_os == "windows":
        paths.append(prefix + "elevate.exe")
    if entry["directory"]:
        for name in paths:
            with (Path(entry["source"]) / name).open("rb") as source:
                check_binary(source, target_os, arm64)
    else:
        with ZipFile(entry["source"]) as archive:
            root = "Sample Desktop.app/" if target_os == "macos" else "app/"
            for name in paths:
                with archive.open(root + name) as source:
                    check_binary(source, target_os, arm64)


def validate_entries(entries):
    apps = [entry for entry in entries if not entry.get("package")]
    if len(apps) != len(ALL_VARIANTS) or {entry["variant"] for entry in apps} != ALL_VARIANTS:
        raise ValueError("Expected exactly seven cross-built app variants")
    if any(entry["variant"] not in ALL_VARIANTS for entry in entries):
        raise ValueError("Unexpected smoke output or variant")
    for entry in apps:
        check_app(entry)


def validate_apps(entries, output):
    validate_entries(entries)
    Path(output).write_bytes(VALIDATED)


def build_bundles(entries, outputs):
    validate_entries(entries)
    if set(outputs) != set(SHARDS):
        raise ValueError("Unexpected smoke output or variant")
    for shard, variants in SHARDS.items():
        write_shard([entry for entry in entries if entry["variant"] in variants], outputs[shard])


def build_shard(entries, output, shard, validation):
    variants = SHARDS.get(shard)
    apps = [entry for entry in entries if not entry.get("package")]
    if (variants is None or len(apps) != len(variants)
            or {entry["variant"] for entry in apps} != set(variants)
            or any(entry["variant"] not in variants for entry in entries)):
        raise ValueError("Smoke entries must match the complete shard")
    if Path(validation).read_bytes() != VALIDATED:
        raise ValueError("Expected successful architecture validation")
    for entry in apps:
        check_app(entry)
    write_shard(entries, output)


def write_shard(entries, output):
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=1) as archive:
        names = set()
        for entry in sorted(entries, key=lambda e: (e["variant"], e["source"])):
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
        info.compress_type = ZIP_STORED if entry.get("package") and file.suffix in (".deb", ".exe", ".AppImage", ".7z", ".lz") else ZIP_DEFLATED
        # Python 3.11 ZipFile.open uses ZipInfo's level, not the archive's.
        info._compresslevel = 1
        with file.open("rb") as content, archive.open(info, "w", force_zip64=True) as destination:
                shutil.copyfileobj(content, destination)
    if entry.get("directory_manifest") and entry["directory"] and not entry.get("package"):
        directories = json.loads(Path(entry["directory_manifest"]).read_text())
        if not isinstance(directories, list) or any(not isinstance(path, str) for path in directories):
            raise ValueError("Expected directory path list")
        for directory in sorted(set(directories)):
            path = PurePosixPath(directory)
            if not path.parts or path.is_absolute() or str(path) != directory or ".." in path.parts or any(c in directory for c in ("\\", ":", "\0")):
                raise ValueError("Invalid smoke directory path")
            name = entry["variant"] + "/app/" + directory + "/"
            if name in names or name[:-1] in names:
                raise ValueError("Duplicate smoke directory member")
            names.add(name)
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
            archive.writestr(info, b"")


if __name__ == "__main__":
    options = json.loads(Path(sys.argv[1]).read_text())
    mode = options.pop("mode", None)
    if mode == "validate":
        validate_apps(**options)
    elif mode == "shard":
        build_shard(**options)
    elif mode is None:
        build_bundles(**options)
    else:
        raise ValueError("Unknown smoke bundle mode")
