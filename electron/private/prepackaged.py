"""Validate imported app metadata without executing or rewriting app bytes."""

import json
from pathlib import Path
import plistlib
import re
import struct
import sys

from electron.private.archive import inventory, relative
from electron.private.asar import read_header
from electron.private.identity import build_identity


def _resolve(name, lookup):
    pending, resolved, expansions = name.split("/"), [], 0
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved:
                raise ValueError("App link escapes its root")
            resolved.pop()
            continue
        key = "/".join(resolved + [part])
        node = lookup(key)
        target = node.get("link") if isinstance(node, dict) else node.target if node.kind == "symlink" else None
        if target is not None:
            expansions += 1
            if expansions > 40:
                raise ValueError("Cyclic app link")
            if not isinstance(target, str) or target.startswith("/") or any(c in target for c in ("\\", ":", "\0")):
                raise ValueError("Invalid app link")
            # ASAR targets are archive-root-relative; filesystem targets are sibling-relative.
            if isinstance(node, dict):
                resolved = []
            pending = target.split("/") + pending
        else:
            if pending and not (isinstance(node, dict) and isinstance(node.get("files"), dict) or not isinstance(node, dict) and node.kind == "directory"):
                raise ValueError("App link traverses a file")
            resolved.append(part)
    return "/".join(resolved)


def _entry(entries, name):
    try:
        entry = entries[_resolve(name, entries.__getitem__)]
    except KeyError as error:
        raise ValueError(f"Missing app file: {name}") from error
    if entry.kind != "file":
        raise ValueError(f"Expected regular app file: {name}")
    return entry


def _asar_package(entries, open_entry, name):
    entry = _entry(entries, name)
    with open_entry(entry) as stream:
        document, _, start = read_header(stream, entry.size)

        def lookup(path):
            node = document
            for part in path.split("/"):
                node = node["files"][part]
                if not isinstance(node, dict):
                    raise ValueError("Invalid ASAR file index")
            return node

        try:
            path = _resolve("package.json", lookup)
            node = lookup(path)
        except KeyError as error:
            raise ValueError("Missing ASAR package.json") from error
        size = node.get("size")
        if type(size) is not int or size < 0 or "files" in node:
            raise ValueError("Invalid ASAR manifest size")
        if node.get("unpacked") is True:
            sidecar = _entry(entries, name + ".unpacked/" + relative(path))
            if sidecar.size != size:
                raise ValueError("ASAR manifest sidecar size mismatch")
            with open_entry(sidecar) as source:
                return json.load(source)
        offset = node.get("offset")
        if not isinstance(offset, str) or not re.fullmatch(r"[0-9]+", offset) or start + int(offset) + size > entry.size:
            raise ValueError("Invalid ASAR manifest offset")
        stream.seek(start + int(offset))
        raw = stream.read(size)
        if len(raw) != size:
            raise ValueError("Truncated ASAR manifest")
        return json.loads(raw)


def _binary(stream, size, platform, cpu):
    def read(offset, count):
        if offset < 0 or offset + count > size:
            raise ValueError("Truncated app executable")
        stream.seek(offset)
        result = stream.read(count)
        if len(result) != count:
            raise ValueError("Truncated app executable")
        return result

    if platform == "linux":
        header = read(0, 64)
        if header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 16)[0] not in (2, 3):
            raise ValueError("Expected ELF64 app executable")
        matches = struct.unpack_from("<H", header, 18)[0] == {"x86_64": 62, "aarch64": 183}[cpu]
    elif platform == "windows":
        header = read(0, 64)
        if header[:2] != b"MZ":
            raise ValueError("Expected PE app executable")
        offset = struct.unpack_from("<I", header, 60)[0]
        pe = read(offset, 26)
        if offset < 64 or pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 24)[0] != 0x20B:
            raise ValueError("Expected PE32+ app executable")
        flags = struct.unpack_from("<H", pe, 22)[0]
        if not flags & 2 or flags & 0x2000:
            raise ValueError("Expected PE executable, not DLL")
        matches = struct.unpack_from("<H", pe, 4)[0] == {"x86_64": 0x8664, "aarch64": 0xAA64}[cpu]
    else:
        expected = {"x86_64": 0x01000007, "aarch64": 0x0100000C}[cpu]

        def thin(offset, length):
            header = read(offset, 32)
            if length < 32 or header[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack_from("<I", header, 12)[0] != 2:
                raise ValueError("Expected Mach-O executable")
            return struct.unpack_from("<I", header, 4)[0]

        magic = read(0, 4)
        if magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
            count = struct.unpack(">I", read(4, 4))[0]
            if not 1 <= count <= 16:
                raise ValueError("Invalid universal Mach-O slice count")
            width = 32 if magic[-1] == 0xBF else 20
            cpus = set()
            for index in range(count):
                record = read(8 + width * index, width)
                declared = struct.unpack_from(">I", record)[0]
                offset, length = struct.unpack_from(">QQ" if width == 32 else ">II", record, 8)
                if offset < 8 + count * width or offset + length > size or thin(offset, length) != declared or declared in cpus:
                    raise ValueError("Invalid universal Mach-O slice")
                cpus.add(declared)
            matches = expected in cpus
        else:
            matches = thin(0, size) == expected
    if not matches:
        raise ValueError("App executable CPU differs from target platform")


def validate(source, package_json, platform, cpu, executable_name, product_name, app_id, build_version="", build_number=""):
    relative(executable_name)
    if "/" in executable_name or cpu not in ("x86_64", "aarch64") or platform not in ("linux", "windows", "macos"):
        raise ValueError("Invalid imported app target or executable name")
    expected = json.loads(Path(package_json).read_text(encoding="utf-8"))
    if not isinstance(expected, dict) or not isinstance(expected.get("name"), str) or not expected["name"]:
        raise ValueError("App manifest requires a package name")
    native_version = build_identity(expected.get("version"), build_version, build_number, platform)
    with inventory(Path(source), platform) as (entries, open_entry):
        resources = "Contents/Resources" if platform == "macos" else "resources"
        asar, plain = resources + "/app.asar", resources + "/app/package.json"
        if asar in entries and plain in entries:
            raise ValueError("Ambiguous app manifests: app and app.asar both present")
        if asar in entries:
            actual = _asar_package(entries, open_entry, asar)
        else:
            with open_entry(_entry(entries, plain)) as stream:
                actual = json.load(stream)
        if not isinstance(actual, dict) or any(actual.get(key, "index.js" if key == "main" else None) != expected.get(key, "index.js" if key == "main" else None) for key in ("name", "version", "main")):
            raise ValueError("Packaged app identity differs from package_json")
        executable = "Contents/MacOS/" + executable_name if platform == "macos" else executable_name + (".exe" if platform == "windows" else "")
        entry = _entry(entries, executable)
        if platform != "windows" and not entry.mode & 0o111:
            raise ValueError("App executable lacks executable mode")
        with open_entry(entry) as stream:
            _binary(stream, entry.size, platform, cpu)
        if platform == "macos":
            with open_entry(_entry(entries, "Contents/Info.plist")) as stream:
                plist = plistlib.load(stream)
            identity = {"CFBundleExecutable": executable_name, "CFBundleIdentifier": app_id, "CFBundleName": product_name, "CFBundleShortVersionString": expected["version"], "CFBundleVersion": native_version}
            if not isinstance(plist, dict) or any(plist.get(key) != value for key, value in identity.items()):
                raise ValueError("macOS bundle identity differs from declared metadata")


if __name__ == "__main__":
    validate(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    Path(sys.argv[2]).write_text("validated\n", encoding="utf-8")
