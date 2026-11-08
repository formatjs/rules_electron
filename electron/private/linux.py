"""Deterministic Linux application payload and freedesktop metadata."""

import gzip
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import struct
import sys
import tarfile
import xml.etree.ElementTree as ET

from electron.private.update import _version
from electron.private.files import read_directories


def _identifier(value, field):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError(f"Invalid {field}")
    return value


def _desktop_string(value):
    return value.replace("\\", "\\\\").replace("\n", r"\n").replace("\r", r"\r").replace("\t", r"\t")


def create_payload(app, package_json, app_id, product_name, executable_name,
                   architecture, revision, description, categories, protocols,
                   file_associations, icons, output, version_output, directory_manifest="", setuid_sandbox=False):
    _identifier(app_id, "app_id")
    _identifier(executable_name, "executable_name")
    if architecture not in ("amd64", "arm64"):
        raise ValueError("Unsupported DEB architecture")
    if not re.fullmatch(r"[A-Za-z0-9.+~]+", revision):
        raise ValueError("Invalid Debian revision")
    package = json.loads(Path(package_json).read_text(encoding="utf-8"))
    version = _version(package.get("version"))
    upstream, separator, prerelease = version.partition("-")
    deb_version = upstream + ("~" + prerelease if separator else "") + "-" + revision
    app = Path(app)
    if not (app / executable_name).is_file():
        raise ValueError("App executable missing")
    if setuid_sandbox:
        helper = app / "chrome-sandbox"
        if executable_name == "chrome-sandbox" or helper.is_symlink() or not helper.is_file() or not helper.stat().st_mode & 0o111:
            raise ValueError("Setuid sandbox requires a separate regular executable chrome-sandbox")
        with helper.open("rb") as source:
            header = source.read(20)
        if (len(header) != 20 or header[:6] != b"\x7fELF\x02\x01"
                or struct.unpack_from("<H", header, 16)[0] not in (2, 3)
                or struct.unpack_from("<H", header, 18)[0] != {"amd64": 62, "arm64": 183}[architecture]):
            raise ValueError("Setuid sandbox must be an ELF64 executable matching the DEB architecture")
    for scheme in protocols:
        if not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme):
            raise ValueError("Invalid URI protocol")
    for category in categories:
        _identifier(category, "desktop category")
    namespace = "http://www.freedesktop.org/standards/shared-mime-info"
    ET.register_namespace("", namespace)
    mime_info = ET.Element("{" + namespace + "}mime-info")
    for mime_type, patterns in sorted(file_associations.items()):
        if not re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", mime_type) or not patterns:
            raise ValueError("Invalid MIME association")
        node = ET.SubElement(mime_info, "{" + namespace + "}mime-type", {"type": mime_type})
        ET.SubElement(node, "{" + namespace + "}comment").text = product_name + " document"
        for pattern in patterns:
            if not pattern or "/" in pattern or "\\" in pattern or any(ord(c) < 32 for c in pattern):
                raise ValueError("Invalid MIME filename glob")
            ET.SubElement(node, "{" + namespace + "}glob", {"pattern": pattern})
    prefix = "opt/" + app_id
    launch = "/" + prefix + "/" + executable_name
    desktop = {
        "Type": "Application", "Name": product_name, "Comment": description,
        "Exec": launch + " %U", "TryExec": launch, "Icon": app_id,
        "Terminal": "false", "Categories": ";".join(categories) + (";" if categories else ""),
        "MimeType": ";".join(["x-scheme-handler/" + p for p in protocols] + sorted(file_associations)) + (";" if protocols or file_associations else ""),
        "StartupWMClass": package.get("name", executable_name),
    }
    generated = {
        prefix + "/resources/package-type": (b"deb\n", 0o644),
        "usr/bin/" + executable_name: (("#!/bin/sh\nexec " + shlex.quote(launch) + ' "$@"\n').encode(), 0o755),
        "usr/share/applications/" + app_id + ".desktop": (("[Desktop Entry]\n" + "\n".join(k + "=" + _desktop_string(v) for k, v in desktop.items()) + "\n").encode(), 0o644),
    }
    if file_associations:
        generated["usr/share/mime/packages/" + app_id + ".xml"] = (ET.tostring(mime_info, encoding="utf-8", xml_declaration=True), 0o644)
    entries, empty = {}, set()
    if directory_manifest:
        empty.update(prefix + "/" + str(path) for path in read_directories(directory_manifest))
    for source in sorted(app.rglob("*")):
        relative = source.relative_to(app)
        if source.is_dir() and not source.is_symlink():
            empty.add(prefix + "/" + relative.as_posix())
            continue
        destination = prefix + "/" + relative.as_posix()
        if destination in generated:
            if source.is_symlink() or source.read_bytes().strip() != b"deb":
                raise ValueError("App has conflicting package-type resource")
            continue
        if source.is_symlink():
            if source.readlink().is_absolute():
                raise ValueError("App symlinks must be relative")
            try:
                source.resolve(strict=True).relative_to(app.resolve())
            except (ValueError, OSError, RuntimeError) as error:
                raise ValueError("App symlink escapes package or is dangling") from error
        elif not source.is_file():
            raise ValueError("Only regular app files and internal symlinks can be packaged")
        entries[destination] = source
    for icon in icons:
        source = Path(icon["source"])
        size = icon["size"]
        if size == "scalable" and source.suffix.lower() == ".svg":
            extension = ".svg"
        elif re.fullmatch(r"[1-9][0-9]*", size) and source.suffix.lower() == ".png":
            size += "x" + size
            extension = ".png"
        else:
            raise ValueError("Icons require PNG pixel size or scalable SVG")
        destination = "usr/share/icons/hicolor/" + size + "/apps/" + app_id + extension
        if destination in entries:
            raise ValueError("Duplicate icon size")
        entries[destination] = source
    directories = empty | {str(parent) for name in [*entries, *generated, *empty] for parent in PurePosixPath(name).parents if str(parent) != "."}
    if directories & (entries.keys() | generated.keys()):
        raise ValueError("Linux payload file/directory collision")
    with Path(output).open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(directories | set(entries) | set(generated)):
                info = tarfile.TarInfo(name)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = "root"
                if name in directories:
                    info.type, info.mode = tarfile.DIRTYPE, 0o755
                    archive.addfile(info)
                elif name in generated:
                    data, info.mode = generated[name]
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
                else:
                    source = entries[name]
                    if source.is_symlink():
                        info.type, info.linkname, info.mode = tarfile.SYMTYPE, source.readlink().as_posix(), 0o777
                        archive.addfile(info)
                    else:
                        info.size = source.stat().st_size
                        info.mode = 0o4755 if setuid_sandbox and name == prefix + "/chrome-sandbox" else 0o755 if source.stat().st_mode & 0o111 else 0o644
                        with source.open("rb") as contents:
                            archive.addfile(info, contents)
    Path(version_output).write_text(deb_version + "\n", encoding="utf-8")


if __name__ == "__main__":
    create_payload(output=sys.argv[2], version_output=sys.argv[3], **json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
