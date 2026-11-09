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
from electron.private.archive import Entry, inventory, resolve
from electron.private.icons import png_dimensions


def _identifier(value, field):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError(f"Invalid {field}")
    return value


def _desktop_string(value):
    return value.replace("\\", "\\\\").replace("\n", r"\n").replace("\r", r"\r").replace("\t", r"\t")


def create_payload(app, package_json, app_id, product_name, executable_name,
                   architecture, revision, description, categories, protocols,
                   file_associations, icons, output, version_output, directory_manifest="", setuid_sandbox=False,
                   file_association_icons=(), package_type="deb"):
    with inventory(Path(app), "linux") as (app_entries, open_app):
        _create_payload(app_entries, open_app, package_json, app_id, product_name, executable_name,
                        architecture, revision, description, categories, protocols, file_associations,
                        icons, output, version_output, directory_manifest, setuid_sandbox, file_association_icons, package_type)


def _create_payload(app_entries, open_app, package_json, app_id, product_name, executable_name,
                    architecture, revision, description, categories, protocols,
                    file_associations, icons, output, version_output, directory_manifest, setuid_sandbox, file_association_icons, package_type):
    if package_type not in ("deb", "rpm"):
        raise ValueError("Unsupported Linux package type")
    _identifier(app_id, "app_id")
    _identifier(executable_name, "executable_name")
    if architecture not in ("amd64", "arm64"):
        raise ValueError("Unsupported Linux package architecture")
    if not re.fullmatch(r"[A-Za-z0-9.+~]+", revision):
        raise ValueError("Invalid Linux package revision")
    package = json.loads(Path(package_json).read_text(encoding="utf-8"))
    version = _version(package.get("version"))
    upstream, separator, prerelease = version.partition("-")
    deb_version = upstream + ("~" + prerelease if separator else "") + "-" + revision
    executable = app_entries.get(executable_name)
    if executable is None or app_entries.get(resolve(app_entries, executable_name), Entry("directory", 0)).kind != "file":
        raise ValueError("App executable missing")
    if setuid_sandbox:
        helper = app_entries.get("chrome-sandbox")
        if executable_name == "chrome-sandbox" or helper is None or helper.kind != "file" or not helper.mode & 0o111:
            raise ValueError("Setuid sandbox requires a separate regular executable chrome-sandbox")
        with open_app(helper) as source:
            header = source.read(20)
        if (len(header) != 20 or header[:6] != b"\x7fELF\x02\x01"
                or struct.unpack_from("<H", header, 16)[0] not in (2, 3)
                or struct.unpack_from("<H", header, 18)[0] != {"amd64": 62, "arm64": 183}[architecture]):
            raise ValueError("Setuid sandbox must be an ELF64 executable matching the Linux package architecture")
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
        prefix + "/resources/package-type": ((package_type + "\n").encode(), 0o644),
        "usr/bin/" + executable_name: (("#!/bin/sh\nexec " + shlex.quote(launch) + ' "$@"\n').encode(), 0o755),
        "usr/share/applications/" + app_id + ".desktop": (("[Desktop Entry]\n" + "\n".join(k + "=" + _desktop_string(v) for k, v in desktop.items()) + "\n").encode(), 0o644),
    }
    if file_associations:
        generated["usr/share/mime/packages/" + app_id + ".xml"] = (ET.tostring(mime_info, encoding="utf-8", xml_declaration=True), 0o644)
    entries, empty = {}, set()
    if directory_manifest:
        empty.update(prefix + "/" + str(path) for path in read_directories(directory_manifest))
    for relative, entry in app_entries.items():
        if entry.kind == "directory":
            empty.add(prefix + "/" + relative)
            continue
        destination = prefix + "/" + relative
        if destination in generated:
            if entry.kind != "file":
                raise ValueError("App has conflicting package-type resource")
            with open_app(entry) as source:
                if source.read().strip() != package_type.encode():
                    raise ValueError("App has conflicting package-type resource")
            continue
        entries[destination] = (entry, open_app)
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
        entries[destination] = (Entry("file", 0o755 if source.stat().st_mode & 0o111 else 0o644, source.stat().st_size, source),
                                lambda entry: entry.source.open("rb"))
    for icon in file_association_icons:
        source, mime_type = Path(icon["source"]), icon["mime_type"]
        if mime_type not in file_associations:
            raise ValueError("File-type icon requires a registered MIME association")
        if source.suffix.lower() == ".png":
            width, height = png_dimensions(source)
            if width != height:
                raise ValueError("File-type PNG icons must be square")
            size = str(width) + "x" + str(height)
        elif source.suffix.lower() == ".svg":
            try:
                tag = ET.parse(source).getroot().tag
            except ET.ParseError as error:
                raise ValueError("Invalid SVG file-type icon") from error
            if tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
                raise ValueError("Expected an SVG file-type icon")
            size = "scalable"
        else:
            raise ValueError("File-type icons require PNG or SVG")
        destination = "usr/share/icons/hicolor/" + size + "/mimetypes/" + mime_type.replace("/", "-") + source.suffix.lower()
        if destination in entries:
            raise ValueError("Duplicate file-type icon size")
        entries[destination] = (Entry("file", 0o644, source.stat().st_size, source), lambda entry: entry.source.open("rb"))
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
                    entry, open_entry = entries[name]
                    if entry.kind == "symlink":
                        info.type, info.linkname, info.mode = tarfile.SYMTYPE, entry.target, 0o777
                        archive.addfile(info)
                    else:
                        info.size = entry.size
                        info.mode = 0o4755 if setuid_sandbox and name == prefix + "/chrome-sandbox" else entry.mode
                        with open_entry(entry) as contents:
                            archive.addfile(info, contents)
    Path(version_output).write_text(deb_version + "\n", encoding="utf-8")


if __name__ == "__main__":
    create_payload(output=sys.argv[2], version_output=sys.argv[3], **json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
