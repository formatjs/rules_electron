"""Declared Finder window settings; no target OS calls or filesystem aliases."""

from pathlib import Path
import re
import struct
from datetime import datetime, timezone

from ds_store import DSStore
from mac_alias import (Alias, TargetInfo, VolumeInfo, ALIAS_EJECTABLE_DISK,
                       ALIAS_HFS_VOLUME_SIGNATURE, ALIAS_KIND_FILE, ALIAS_NO_CNID)


def background_identity(image):
    with Path(image).open("rb") as source:
        size = source.seek(0, 2)

        def read(offset, length):
            if not 0 <= offset <= size or not 0 <= length <= size - offset:
                raise ValueError("Invalid HFS+ metadata bounds")
            source.seek(offset)
            data = source.read(length)
            if len(data) != length:
                raise ValueError("Truncated HFS+ metadata")
            return data

        count = struct.unpack_from(">I", read(512, 512), 4)[0]
        if not 1 <= count <= 128:
            raise ValueError("Invalid HFS+ partition count")
        partitions = [read(index * 512, 512) for index in range(1, count + 1)]
        volumes = [struct.unpack_from(">I", entry, 8)[0] * 512 for entry in partitions
                   if entry[:2] == b"PM" and entry[48:80].rstrip(b"\0") == b"Apple_HFS"]
        if len(volumes) != 1:
            raise ValueError("Expected one HFS+ partition")
        volume = volumes[0]
        header = read(volume + 1024, 512)
        block_size = struct.unpack_from(">I", header, 40)[0]
        if header[:2] != b"H+" or not 512 <= block_size <= 65536 or block_size & (block_size - 1):
            raise ValueError("Invalid HFS+ volume header")
        catalog_size = struct.unpack_from(">Q", header, 272)[0]
        first_block, blocks = struct.unpack_from(">II", header, 288)
        if not 512 <= catalog_size <= 64 * 1024**2 or blocks * block_size < catalog_size:
            raise ValueError("Unsupported HFS+ catalog extent")
        catalog = read(volume + first_block * block_size, catalog_size)
    node_size = struct.unpack_from(">H", catalog, 32)[0]
    node = struct.unpack_from(">I", catalog, 24)[0]
    if not 512 <= node_size <= 32768 or node_size & (node_size - 1):
        raise ValueError("Invalid HFS+ catalog node size")
    visited, matches = set(), []
    while node:
        if node in visited or node * node_size + node_size > len(catalog):
            raise ValueError("Invalid HFS+ catalog chain")
        visited.add(node)
        leaf = catalog[node * node_size:(node + 1) * node_size]
        count = struct.unpack_from(">H", leaf, 10)[0]
        if leaf[8] != 0xff or 14 + 2 * (count + 1) > node_size:
            raise ValueError("Invalid HFS+ catalog leaf")
        for index in range(count):
            offset = struct.unpack_from(">H", leaf, node_size - 2 * (index + 1))[0]
            if not 14 <= offset <= node_size - 8:
                raise ValueError("Invalid HFS+ catalog record")
            key_size, parent, name_size = struct.unpack_from(">HIH", leaf, offset)
            data = offset + 2 + key_size
            if key_size != 6 + 2 * name_size or data + 2 > node_size - 2 * (count + 1):
                raise ValueError("Invalid HFS+ catalog key")
            if parent == 2 and leaf[offset + 8:data].decode("utf-16be") == ".background.png":
                if data + 16 > node_size - 2 * (count + 1):
                    raise ValueError("Truncated HFS+ background record")
                kind = struct.unpack_from(">H", leaf, data)[0]
                identity, created = struct.unpack_from(">II", leaf, data + 8)
                if kind != 2 or identity < 16:
                    raise ValueError("Invalid HFS+ background file")
                matches.append((identity, created - 2082844800))
        node = struct.unpack_from(">I", leaf)[0]
    if len(matches) != 1:
        raise ValueError("Expected one HFS+ background file")
    return matches[0]


def background_alias(volume_name, source_date_epoch, file_identity=ALIAS_NO_CNID, file_date=None):
    date = datetime.fromtimestamp(source_date_epoch, timezone.utc)
    volume = VolumeInfo(name=volume_name, creation_date=date,
                        fs_type=ALIAS_HFS_VOLUME_SIGNATURE, disk_type=ALIAS_EJECTABLE_DISK,
                        attribute_flags=0, fs_id=b"\0\0")
    target = TargetInfo(kind=ALIAS_KIND_FILE, filename=".background.png", folder_cnid=2,
                        cnid=file_identity, creation_date=datetime.fromtimestamp(file_date, timezone.utc) if file_date is not None else date,
                        creator_code=b"\0" * 4,
                        type_code=b"\0" * 4,
                        posix_path="/.background.png", carbon_path=volume_name + ":.background.png")
    return Alias(volume=volume, target=target).to_bytes()


def write_layout(output, app_name, applications_link, window, app_position, applications_position,
                 icon_size, text_size, background_color, image_alias=b""):
    if len(window) != 4 or any(type(value) is not int for value in window):
        raise ValueError("Finder window requires x, y, width and height integers")
    x, y, width, height = window
    if not (-32768 <= x <= 32767 and -32768 <= y <= 32767 and 1 <= width <= 32767 and 1 <= height <= 32767):
        raise ValueError("Finder window bounds exceed supported range")
    positions = {app_name: app_position}
    if applications_link:
        positions["Applications"] = applications_position
    for point in positions.values():
        if (len(point) != 2 or any(type(value) is not int for value in point)
                or not 0 <= point[0] < width or not 0 <= point[1] < height):
            raise ValueError("Finder icon position must lie inside the window")
    if type(icon_size) is not int or not 16 <= icon_size <= 512:
        raise ValueError("Finder icon size must be 16..512")
    if type(text_size) is not int or not 10 <= text_size <= 16:
        raise ValueError("Finder text size must be 10..16")
    if not isinstance(background_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", background_color):
        raise ValueError("Finder background color requires #RRGGBB")
    red, green, blue = (int(background_color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    with DSStore.open(str(output), "w+") as store:
        store["."]["vSrn"] = ("long", 1)
        store["."]["icvl"] = ("type", b"icnv")
        store["."]["bwsp"] = {
            "WindowBounds": "{{%d, %d}, {%d, %d}}" % (x, y, width, height),
            "ShowToolbar": False, "ShowStatusBar": False, "ShowSidebar": False,
            "ShowTabView": False, "ShowPathbar": False, "ContainerShowSidebar": False,
            "PreviewPaneVisibility": False, "SidebarWidth": 0,
        }
        settings = {
            "viewOptionsVersion": 1, "arrangeBy": "none", "iconSize": float(icon_size),
            "textSize": float(text_size), "labelOnBottom": True, "showItemInfo": False,
            "showIconPreview": False, "gridOffsetX": 0.0, "gridOffsetY": 0.0,
            "gridSpacing": 100.0, "scrollPositionX": 0.0, "scrollPositionY": 0.0,
            "backgroundType": 1, "backgroundColorRed": red,
            "backgroundColorGreen": green, "backgroundColorBlue": blue,
        }
        if image_alias:
            settings.update(backgroundType=2, backgroundImageAlias=image_alias)
        store["."]["icvp"] = settings
        for name, point in sorted(positions.items()):
            store[name]["Iloc"] = tuple(point)
    Path(output).chmod(0o644)
