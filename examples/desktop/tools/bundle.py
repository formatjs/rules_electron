import json
from pathlib import Path
import shutil
import sys
import struct
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED


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


if __name__ == "__main__":
    entries = json.loads(Path(sys.argv[1]).read_text())
    with ZipFile(sys.argv[2], "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for entry in sorted(entries, key=lambda e: e["variant"]):
            check_app(entry)
            source = Path(entry["source"])
            files = sorted(source.rglob("*")) if entry["directory"] else [source]
            for file in files:
                if file.is_dir():
                    continue
                name = entry["variant"] + "/" + ("app/" + file.relative_to(source).as_posix() if entry["directory"] else "app.zip")
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = file.stat().st_mode << 16
                info.compress_type = ZIP_DEFLATED
                with file.open("rb") as content, archive.open(info, "w", force_zip64=True) as destination:
                    shutil.copyfileobj(content, destination)
