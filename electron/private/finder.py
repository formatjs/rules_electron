"""Declared Finder window settings; no target OS calls or filesystem aliases."""

from pathlib import Path
import re
from datetime import datetime, timezone

from ds_store import DSStore
from mac_alias import (Alias, TargetInfo, VolumeInfo, ALIAS_EJECTABLE_DISK,
                       ALIAS_HFS_VOLUME_SIGNATURE, ALIAS_KIND_FILE, ALIAS_NO_CNID)


def background_alias(volume_name, source_date_epoch):
    date = datetime.fromtimestamp(source_date_epoch, timezone.utc)
    volume = VolumeInfo(name=volume_name, creation_date=date,
                        fs_type=ALIAS_HFS_VOLUME_SIGNATURE, disk_type=ALIAS_EJECTABLE_DISK,
                        attribute_flags=0, fs_id=b"\0\0", posix_path="/Volumes/" + volume_name)
    target = TargetInfo(kind=ALIAS_KIND_FILE, filename=".background.png", folder_cnid=2,
                        cnid=ALIAS_NO_CNID, creation_date=date, creator_code=b"\0" * 4,
                        type_code=b"\0" * 4, folder_name=volume_name,
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
