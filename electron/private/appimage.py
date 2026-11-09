"""Declared AppDir assembly and deterministic type-2 AppImage packaging."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib

from electron.private.archive import Entry, inventory, resolve, validate
from electron.private.files import read_directories
from electron.private.icons import png_dimensions
from electron.private.linux import _desktop_string, _identifier
from electron.private.update import _content_chunks, _version


def elf_prefix(path, architecture, runtime=False):
    data = bytearray(Path(path).read_bytes())
    if (len(data) < 64 or data[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<H", data, 18)[0] != {"x64": 62, "arm64": 183}[architecture]):
        raise ValueError("AppImage executable must be ELF64 matching target CPU")
    if not runtime:
        if struct.unpack_from("<H", data, 16)[0] not in (2, 3):
            raise ValueError("Invalid AppImage payload executable type")
        return data
    if struct.unpack_from("<H", data, 16)[0] != 3:
        raise ValueError("AppImage runtime must be static PIE")
    phoff, shoff = struct.unpack_from("<QQ", data, 32)
    phsize, phcount, shsize, shcount = struct.unpack_from("<HHHH", data, 54)
    if phsize != 56 or shsize != 64 or not phcount or not shcount or max(phoff + phsize * phcount, shoff + shsize * shcount) > len(data):
        raise ValueError("Invalid runtime ELF tables")
    last = shoff + shsize * (shcount - 1)
    offset = max(shoff + shsize * shcount, sum(struct.unpack_from("<QQ", data, last + 24)))
    if offset > len(data):
        raise ValueError("Truncated runtime ELF sections")
    for index in range(shcount):
        position = shoff + index * shsize
        kind = struct.unpack_from("<I", data, position + 4)[0]
        if kind != 8 and sum(struct.unpack_from("<QQ", data, position + 24)) > offset:
            raise ValueError("Runtime section lies beyond payload offset")
    for index in range(phcount):
        position = phoff + index * phsize
        kind = struct.unpack_from("<I", data, position)[0]
        start = struct.unpack_from("<Q", data, position + 8)[0]
        size = struct.unpack_from("<Q", data, position + 32)[0]
        if start + size > offset or kind == 3:
            raise ValueError("AppImage runtime needs self-contained ELF segments")
        if kind == 2:
            if size % 16:
                raise ValueError("Invalid runtime dynamic table")
            for cursor in range(start, start + size, 16):
                if struct.unpack_from("<Q", data, cursor)[0] == 1:
                    raise ValueError("AppImage runtime cannot import shared libraries")
    data[8:11] = b"AI\x02"
    return data[:offset]


def append_blockmap(path):
    checksums, sizes = [], []
    with Path(path).open("rb") as source:
        for chunk in _content_chunks(source):
            checksums.append(base64.b64encode(hashlib.sha256(chunk).digest()).decode())
            sizes.append(len(chunk))
    blockmap = dict(version="2", files=[dict(name="file", offset=0, checksums=checksums, sizes=sizes)])
    compressor = zlib.compressobj(level=9, wbits=-15)
    raw = json.dumps(blockmap, separators=(",", ":")).encode()
    compressed = compressor.compress(raw) + compressor.flush()
    if len(compressed) > 0xffffffff:
        raise ValueError("AppImage blockmap exceeds trailer capacity")
    with Path(path).open("ab") as output:
        output.write(compressed)
        output.write(struct.pack(">I", len(compressed)))


def create_appimage(app, runtime, launcher, mksquashfs, output, app_id, product_name,
                    executable_name, architecture, icon, description="", categories=("Utility",),
                    protocols=(), file_associations=(), directory_manifest="", compressor="zstd",
                    compression_level=9, embedded_blockmap=True):
    _identifier(app_id, "app_id")
    _identifier(executable_name, "executable_name")
    if len(executable_name) > 255:
        raise ValueError("AppImage executable basename exceeds NAME_MAX")
    if architecture not in ("x64", "arm64") or compressor not in ("gzip", "zstd"):
        raise ValueError("Unsupported AppImage CPU or compressor")
    if not 1 <= compression_level <= (9 if compressor == "gzip" else 22):
        raise ValueError("Invalid AppImage compression level")
    for category in categories:
        _identifier(category, "desktop category")
    for scheme in protocols:
        if not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme):
            raise ValueError("Invalid URI protocol")
    for mime in file_associations:
        if not re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", mime):
            raise ValueError("Invalid MIME association")
    icon = Path(icon)
    extension = icon.suffix.lower()
    if extension == ".png":
        png_dimensions(icon)
    elif extension == ".svg":
        if ET.parse(icon).getroot().tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
            raise ValueError("Invalid AppImage SVG icon")
    else:
        raise ValueError("AppImage icon must be PNG or SVG")
    prefix = elf_prefix(runtime, architecture, runtime=True)
    elf_prefix(launcher, architecture, runtime=True)
    with inventory(Path(app), "linux") as (entries, open_app), tempfile.TemporaryDirectory() as temporary:
        if directory_manifest:
            for name in map(str, read_directories(directory_manifest)):
                if name in entries and entries[name].kind != "directory":
                    raise ValueError("AppImage directory metadata collides with file")
                entries.setdefault(name, Entry("directory", 0o755))
            validate(entries, "linux")
        if executable_name not in entries or entries[resolve(entries, executable_name)].kind != "file":
            raise ValueError("AppImage executable missing")
        with open_app(entries[resolve(entries, executable_name)]) as source:
            header = source.read(64)
        if (len(header) < 64 or header[:6] != b"\x7fELF\x02\x01"
                or struct.unpack_from("<H", header, 16)[0] not in (2, 3)
                or struct.unpack_from("<H", header, 18)[0] != {"x64": 62, "arm64": 183}[architecture]
                or not entries[resolve(entries, executable_name)].mode & 0o111):
            raise ValueError("AppImage payload executable must match target CPU")
        reserved = {"AppRun", ".electron-executable", ".DirIcon", app_id + ".desktop", app_id + extension}
        if reserved & entries.keys():
            raise ValueError("AppImage reserved path collision")
        root = Path(temporary)
        appdir = root / "AppDir"
        appdir.mkdir(mode=0o755)
        for name, entry in sorted(entries.items()):
            destination = appdir / name
            if entry.kind == "directory":
                destination.mkdir(parents=True, exist_ok=True)
                destination.chmod(0o755)
            elif entry.kind == "file":
                destination.parent.mkdir(parents=True, exist_ok=True)
                with open_app(entry) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                destination.chmod(entry.mode)
        for name, entry in sorted(entries.items()):
            if entry.kind == "symlink":
                (appdir / name).symlink_to(entry.target)
        shutil.copyfile(launcher, appdir / "AppRun")
        (appdir / "AppRun").chmod(0o755)
        (appdir / ".electron-executable").write_text(executable_name + "\n")
        shutil.copyfile(icon, appdir / (app_id + extension))
        (appdir / ".DirIcon").symlink_to(app_id + extension)
        desktop = dict(Type="Application", Name=product_name, Comment=description,
                       Exec=executable_name + " %U", TryExec=executable_name, Icon=app_id,
                       Terminal="false", Categories=";".join(categories) + (";" if categories else ""),
                       MimeType=";".join(["x-scheme-handler/" + scheme for scheme in protocols] + list(file_associations)) + (";" if protocols or file_associations else ""))
        (appdir / (app_id + ".desktop")).write_text("[Desktop Entry]\n" + "".join(key + "=" + _desktop_string(value) + "\n" for key, value in desktop.items()))
        for name in [".electron-executable", app_id + extension, app_id + ".desktop"]:
            (appdir / name).chmod(0o644)
        filesystem = root / "filesystem.squashfs"
        subprocess.run([str(Path(mksquashfs).resolve()), str(appdir), str(filesystem), "-noappend", "-no-progress",
                        "-no-xattrs", "-all-root", "-all-time", "0", "-mkfs-time", "0", "-processors", "2",
                        "-mem", "64M", "-comp", compressor, "-Xcompression-level", str(compression_level)],
                       env={"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC"}, check=True)
        with Path(output).open("wb") as target, filesystem.open("rb") as source:
            target.write(prefix)
            shutil.copyfileobj(source, target, 1024 * 1024)
    if embedded_blockmap:
        append_blockmap(output)
    Path(output).chmod(0o755)
    os.utime(output, (0, 0))


if __name__ == "__main__":
    manifest = json.loads(Path(sys.argv[1]).read_text())
    _version(json.loads(Path(manifest.pop("package_json")).read_text())["version"])
    create_appimage(output=sys.argv[2], **manifest)
