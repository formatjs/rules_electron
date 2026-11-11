"""Declared MSIX manifest, ZIP64 container and independently hashed 64 KiB blocks."""

import base64
import cProfile
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import pstats
import re
import shutil
import struct
import sys
import tempfile
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET
import zlib

from electron.private.archive import inventory
from electron.private.files import read_directories
from electron.private.icons import png_dimensions
from electron.private.identity import build_identity

BLOCK = "http://schemas.microsoft.com/appx/2010/blockmap"
CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
FOUNDATION = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
UAP3 = "http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
RESCAP = "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
FOOTPRINTS = {"appxmanifest.xml", "appxblockmap.xml", "[content_types].xml", "appxsignature.p7x", "appxmetadata"}


def xml(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def text(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 or 0xd800 <= ord(c) <= 0xdfff or ord(c) in (0xfffe, 0xffff) for c in value):
        raise ValueError("MSIX text must be nonempty XML text without controls")
    return value


def payload_name(name):
    if len(name.encode("utf-16-le")) > 520:
        raise ValueError("MSIX payload path exceeds 260 UTF-16 units")
    for part in name.split("/"):
        if (not part or part in (".", "..") or part[-1] in (".", " ")
                or re.search(r'[<>:"|?*\\\x00-\x1f]', part)
                or re.fullmatch(r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)):
            raise ValueError("Invalid MSIX payload path")
    text(name)
    if name.split("/", 1)[0].casefold() in FOOTPRINTS:
        raise ValueError("MSIX payload occupies reserved footprint path")


class PackageZip:
    """ZIP64 records with known lengths; no host archiver or target execution."""

    def __init__(self, output):
        self.output = output
        self.records = []
        self.blockmap = ET.Element("BlockMap", xmlns=BLOCK, HashMethod="http://www.w3.org/2001/04/xmlenc#sha256")
        self.content = ET.Element("Types", xmlns=CONTENT)

    def add(self, name, source, content_type, *, hashed=True, compressed=True):
        encoded = quote(name, safe="/-._~").encode("ascii")
        # Footprint spelling is fixed by OPC rather than URI encoding.
        if name == "[Content_Types].xml":
            encoded = name.encode("ascii")
        if len(encoded) > 65535:
            raise ValueError("MSIX ZIP name exceeds header capacity")
        node = ET.Element("File", Name=name.replace("/", "\\"), Size="0", LfhSize=str(50 + len(encoded)))
        compressor = zlib.compressobj(9, zlib.DEFLATED, -15, 9) if compressed else None
        crc, size = 0, 0
        with tempfile.TemporaryFile() as packed:
            while True:
                block = source.read(65536)
                if not block:
                    break
                size += len(block)
                crc = zlib.crc32(block, crc)
                chunk = compressor.compress(block) + compressor.flush(zlib.Z_FULL_FLUSH) if compressor else block
                packed.write(chunk)
                if hashed:
                    attributes = dict(Hash=base64.b64encode(hashlib.sha256(block).digest()).decode("ascii"))
                    if compressed:
                        attributes["Size"] = str(len(chunk))
                    ET.SubElement(node, "Block", **attributes)
            if compressor:
                packed.write(compressor.flush(zlib.Z_FINISH))
            compressed_size = packed.tell()
            offset = self.output.tell()
            method = 8 if compressed else 0
            extra = struct.pack("<HHQQ", 1, 16, size, compressed_size)
            header = struct.pack("<IHHHHHIIIHH", 0x04034b50, 45, 0x800, method, 0, 33, crc, 0xffffffff, 0xffffffff, len(encoded), len(extra))
            self.output.write(header + encoded + extra)
            packed.seek(0)
            shutil.copyfileobj(packed, self.output, 1024 * 1024)
        self.records.append((encoded, method, crc, size, compressed_size, offset))
        if hashed:
            node.set("Size", str(size))
            self.blockmap.append(node)
        if content_type:
            ET.SubElement(self.content, "Override", PartName="/" + encoded.decode("ascii"), ContentType=content_type)
        return offset + len(header) + len(encoded) + len(extra), size

    def close(self):
        self.add("AppxBlockMap.xml", io.BytesIO(xml(self.blockmap)), "application/vnd.ms-appx.blockmap+xml", hashed=False)
        self.add("[Content_Types].xml", io.BytesIO(xml(self.content)), None, hashed=False)
        start = self.output.tell()
        for name, method, crc, size, compressed_size, offset in self.records:
            extra = struct.pack("<HHQQQ", 1, 24, size, compressed_size, offset)
            self.output.write(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014b50, 45, 45, 0x800, method, 0, 33,
                                          crc, 0xffffffff, 0xffffffff, len(name), len(extra), 0, 0, 0, 0, 0xffffffff) + name + extra)
        length = self.output.tell() - start
        end = self.output.tell()
        count = len(self.records)
        self.output.write(struct.pack("<IQHHIIQQQQ", 0x06064b50, 44, 45, 45, 0, 0, count, count, length, start))
        self.output.write(struct.pack("<IIQI", 0x07064b50, 0, end, 1))
        self.output.write(struct.pack("<IHHHHIIH", 0x06054b50, 0, 0, 0xffff, 0xffff, 0xffffffff, 0xffffffff, 0))


def manifest(identity_name, publisher, publisher_display_name, product_name, executable,
             architecture, version, description, protocols=(), file_associations=None, file_association_icons=()):
    if not re.fullmatch(r"[A-Za-z0-9.-]{3,50}", identity_name):
        raise ValueError("MSIX identity name requires 3..50 ASCII letters, digits, dots or hyphens")
    if architecture not in ("x64", "arm64"):
        raise ValueError("MSIX supports x64/arm64")
    if len(set(protocols)) != len(protocols) or any(not re.fullmatch(r"[a-z][a-z0-9+.-]{1,2047}", scheme) for scheme in protocols):
        raise ValueError("MSIX protocols require distinct lowercase URI schemes of 2..2048 characters")
    associations = file_associations or {}
    if any(not re.fullmatch(r"\.[a-z0-9][a-z0-9_-]{0,31}", extension) for extension in associations):
        raise ValueError("MSIX file associations require lowercase file extensions")
    if not set(file_association_icons).issubset(associations):
        raise ValueError("MSIX document icons require registered file extensions")
    namespaces = {"xmlns:uap": UAP, "xmlns:rescap": RESCAP, "IgnorableNamespaces": "uap rescap"}
    if protocols or associations:
        namespaces.update({"xmlns:uap3": UAP3, "IgnorableNamespaces": "uap uap3 rescap"})
    root = ET.Element("Package", xmlns=FOUNDATION, **namespaces)
    ET.SubElement(root, "Identity", Name=identity_name, Publisher=text(publisher), Version=version, ProcessorArchitecture=architecture)
    properties = ET.SubElement(root, "Properties")
    for name, value in [("DisplayName", product_name), ("PublisherDisplayName", publisher_display_name), ("Description", description), ("Logo", "Assets/StoreLogo.png")]:
        ET.SubElement(properties, name).text = text(value)
    dependencies = ET.SubElement(root, "Dependencies")
    ET.SubElement(dependencies, "TargetDeviceFamily", Name="Windows.Desktop", MinVersion="10.0.17763.0", MaxVersionTested="10.0.26100.0")
    ET.SubElement(root, "Resources").append(ET.Element("Resource", Language="en-us"))
    application = ET.SubElement(ET.SubElement(root, "Applications"), "Application", Id="App", Executable=executable, EntryPoint="Windows.FullTrustApplication")
    visual = ET.SubElement(application, "uap:VisualElements", DisplayName=text(product_name), Description=text(description), BackgroundColor="transparent", Square150x150Logo="Assets/Square150x150Logo.png", Square44x44Logo="Assets/Square44x44Logo.png")
    ET.SubElement(visual, "uap:DefaultTile")
    if protocols or associations:
        extensions = ET.SubElement(application, "Extensions")
        for scheme in sorted(protocols):
            extension = ET.SubElement(extensions, "uap3:Extension", Category="windows.protocol")
            protocol = ET.SubElement(extension, "uap3:Protocol", Name=scheme, Parameters='"%1"')
            ET.SubElement(protocol, "uap:DisplayName").text = text(product_name)
        for suffix, description in sorted(associations.items()):
            extension = ET.SubElement(extensions, "uap:Extension", Category="windows.fileTypeAssociation")
            name = "file" + hashlib.sha256(suffix.encode()).hexdigest()[:16]
            association = ET.SubElement(extension, "uap3:FileTypeAssociation", Name=name, Parameters='"%1"', MultiSelectModel="Single")
            ET.SubElement(association, "uap:DisplayName").text = text(description)
            if suffix in file_association_icons:
                ET.SubElement(association, "uap:Logo").text = "Assets/FileType" + hashlib.sha256(suffix.encode()).hexdigest()[:16] + ".png"
            ET.SubElement(ET.SubElement(association, "uap:SupportedFileTypes"), "uap:FileType").text = suffix
    ET.SubElement(ET.SubElement(root, "Capabilities"), "rescap:Capability", Name="runFullTrust")
    return xml(root)


def supplied_manifest(path, identity_name, publisher, publisher_display_name, executable, architecture, version, files):
    data = Path(path).read_bytes()
    if len(data) > 1024**2 or b"\0" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("MSIX manifest exceeds limits or declares entities")
    root = ET.fromstring(data)
    if root.tag != "{" + FOUNDATION + "}Package":
        raise ValueError("Expected Windows package manifest")
    identities = root.findall("{" + FOUNDATION + "}Identity")
    expected = dict(Name=identity_name, Publisher=publisher, Version=version, ProcessorArchitecture=architecture)
    if len(identities) != 1 or any(identities[0].get(key) != value for key, value in expected.items()):
        raise ValueError("MSIX manifest identity differs from declared package")
    publishers = root.findall("{" + FOUNDATION + "}Properties/{" + FOUNDATION + "}PublisherDisplayName")
    if len(publishers) != 1 or publishers[0].text != publisher_display_name:
        raise ValueError("MSIX publisher display name differs from declared package")
    applications = root.findall("{" + FOUNDATION + "}Applications/{" + FOUNDATION + "}Application")
    if len(applications) != 1 or applications[0].get("Executable", "").replace("\\", "/") != executable or applications[0].get("EntryPoint") != "Windows.FullTrustApplication":
        raise ValueError("MSIX manifest executable differs from app")
    if not any(node.get("Name") == "runFullTrust" for node in root.findall("{" + FOUNDATION + "}Capabilities/{" + RESCAP + "}Capability")):
        raise ValueError("MSIX desktop app requires runFullTrust")
    for node in root.iter():
        references = [value for key, value in node.attrib.items() if key in ("Logo", "Square44x44Logo", "Square150x150Logo", "Wide310x150Logo", "Square310x310Logo", "Square71x71Logo")]
        if node.tag == "{" + FOUNDATION + "}Logo" or node.tag.endswith("}Logo"):
            references.append(node.text or "")
        for value in references:
            name = value.replace("\\", "/")
            payload_name(name)
            if name not in files:
                raise ValueError("MSIX manifest asset missing from payload: " + name)
    return data


def create_msix(app, package_json, output, identity_name, publisher, publisher_display_name,
                product_name, executable_name, architecture, logo_44="", logo_150="", store_logo="",
                description="Electron desktop application", build_version="", build_number="", directory_manifest="",
                protocols=(), file_associations=None, file_association_icons=(), manifest_file="", payload_prefix="", app_is_tree=False, resources_pri="", package_version=""):
    package = json.loads(Path(package_json).read_text(encoding="utf-8"))
    native_version = package_version or build_identity(package["version"], build_version, build_number, "windows")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", native_version):
        raise ValueError("MSIX prerelease versions require an explicit numeric build_version")
    components = native_version.split(".")
    if any(int(value) > 65535 for value in components):
        raise ValueError("MSIX version components exceed 65535")
    version = ".".join(components + ["0"] * (4 - len(components)))
    executable = executable_name if executable_name.endswith(".exe") else executable_name + ".exe"
    payload_name(executable)
    icons = {}
    for icon in file_association_icons:
        extension = icon["extension"]
        if extension in icons:
            raise ValueError("Duplicate MSIX document icon extension")
        icons[extension] = icon["source"]
    if payload_prefix:
        payload_name(payload_prefix)
        executable = payload_prefix + "/" + executable
    manifest_data = None if manifest_file else manifest(identity_name, publisher, publisher_display_name, product_name, executable, architecture, version, description,
                             protocols, file_associations, icons)
    assets = {"Assets/Square44x44Logo.png": (logo_44, 44), "Assets/Square150x150Logo.png": (logo_150, 150), "Assets/StoreLogo.png": (store_logo, 50)}
    assets = {name: value for name, value in assets.items() if value[0]}
    if not manifest_file and len(assets) != 3:
        raise ValueError("Generated MSIX manifests require all three logos")
    for extension, source in icons.items():
        assets["Assets/FileType" + hashlib.sha256(extension.encode()).hexdigest()[:16] + ".png"] = (source, None)
    for path, dimension in assets.values():
        dimensions = png_dimensions(path)
        if dimension is not None and dimensions != (dimension, dimension):
            raise ValueError("MSIX logo dimensions must match declared asset slot")
    with inventory(Path(app), "windows", declared_tree=app_is_tree) as (entries, open_file), ExitStack() as stack:
        if directory_manifest:
            declared = read_directories(directory_manifest)
            if any(not any(name.startswith(str(directory) + "/") for name in entries) for directory in declared):
                raise ValueError("MSIX empty directory payloads are not supported yet")
        if payload_prefix:
            entries = {payload_prefix + "/" + name: entry for name, entry in entries.items()}
        names = {name.casefold() for name in entries}
        if any(name.casefold() in names for name in assets) or "assets" in names and entries[next(name for name in entries if name.casefold() == "assets")].kind != "directory":
            raise ValueError("MSIX asset path collision")
        for name, entry in entries.items():
            payload_name(name)
            if entry.kind == "symlink":
                raise ValueError("MSIX payload symlinks are not supported")
            if entry.kind == "directory" and not any(other.startswith(name + "/") for other in entries):
                raise ValueError("MSIX empty directory payloads are not supported yet")
        if executable not in entries or entries[executable].kind != "file":
            raise ValueError("MSIX executable missing")
        with open_file(entries[executable]) as binary:
            header = binary.read(64)
            if len(header) != 64 or header[:2] != b"MZ":
                raise ValueError("MSIX executable must be target PE")
            binary.seek(struct.unpack_from("<I", header, 60)[0])
            pe = binary.read(6)
            if pe != b"PE\0\0" + struct.pack("<H", {"x64": 0x8664, "arm64": 0xaa64}[architecture]):
                raise ValueError("MSIX executable CPU differs from target")
        if resources_pri and "resources.pri" in names:
            raise ValueError("MSIX resource index collides with app payload")
        if manifest_file:
            manifest_data = supplied_manifest(manifest_file, identity_name, publisher, publisher_display_name, executable, architecture, version,
                                              {name for name, entry in entries.items() if entry.kind == "file"} | set(assets))
        output_stream = stack.enter_context(Path(output).open("wb"))
        writer = PackageZip(output_stream)
        for name, entry in sorted(entries.items()):
            if entry.kind == "file":
                with open_file(entry) as source:
                    writer.add(name, source, "application/octet-stream")
        for name, (path, _) in sorted(assets.items()):
            with Path(path).open("rb") as source:
                writer.add(name, source, "image/png")
        if resources_pri:
            with Path(resources_pri).open("rb") as source:
                writer.add("resources.pri", source, "application/octet-stream")
        writer.add("AppxManifest.xml", io.BytesIO(manifest_data), "application/vnd.ms-appx.manifest+xml")
        writer.close()


def profile_msix(options, output, report_path):
    """Record one real packaging action without changing its output bytes."""
    profiler = cProfile.Profile()
    wall, cpu = time.perf_counter(), time.process_time()
    profiler.runcall(create_msix, output=output, **options)
    cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
    functions = [dict(file=Path(filename).name, line=line, function=name,
                      primitive_calls=primitive, calls=calls, self_seconds=own, cumulative_seconds=total)
                 for (filename, line, name), (primitive, calls, own, total, _) in pstats.Stats(profiler).stats.items()]
    functions.sort(key=lambda row: row["self_seconds"], reverse=True)
    report = dict(wall_seconds=wall, cpu_seconds=cpu, output_bytes=Path(output).stat().st_size,
                  compression_level=9, block_bytes=65536, functions=functions)
    Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("MSIX_PROFILE " + json.dumps(dict(report, functions=functions[:15])), file=sys.stderr)


if __name__ == "__main__":
    options = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if len(sys.argv) == 4:
        profile_msix(options, sys.argv[2], sys.argv[3])
    else:
        create_msix(output=sys.argv[2], **options)
