"""Read BB-generated DMG settings through the matching native Finder."""

import json
from pathlib import Path
import re
import platform
import plistlib
import subprocess
import sys


SCRIPT = '''
on run argv
    set targetFolder to (POSIX file (item 1 of argv)) as alias
    set targetWindow to missing value
    tell application "Finder"
        try
            open targetFolder
            set targetWindow to container window of targetFolder
            delay 1
            set viewSettings to icon view options of targetWindow
            set snapshot to {(current view of targetWindow is icon view), bounds of targetWindow, toolbar visible of targetWindow, statusbar visible of targetWindow, icon size of viewSettings, text size of viewSettings, background color of viewSettings, position of item "Sample Desktop.app" of targetFolder, position of item "Applications" of targetFolder, bounds of window of desktop}
            close targetWindow
            return snapshot
        on error messageText number messageNumber
            if targetWindow is not missing value then close targetWindow
            error messageText number messageNumber
        end try
    end tell
end run
'''

ICON_SCRIPT = '''
ObjC.import('AppKit');
function sample(path) {
    const image = $.NSWorkspace.sharedWorkspace.iconForFile($(path));
    const bitmap = $.NSBitmapImageRep.imageRepWithData(image.TIFFRepresentation);
    const width = Number(bitmap.pixelsWide), height = Number(bitmap.pixelsHigh);
    const samples = [];
    for (const x of [0.25, 0.5, 0.75]) {
        for (const y of [0.25, 0.5, 0.75]) {
            const color = bitmap.colorAtXY(Math.floor(width * x), Math.floor(height * y))
                .colorUsingColorSpace($.NSColorSpace.sRGBColorSpace);
            samples.push([color.redComponent, color.greenComponent, color.blueComponent, color.alphaComponent]
                .map(value => Math.round(Number(value) * 255)));
        }
    }
    return {width, height, samples};
}
function run(argv) {
    return JSON.stringify({volume: sample(argv[0]), application: sample(argv[1])});
}
'''


def check_layout(mount):
    if platform.system() != "Darwin" or platform.machine().lower() != "arm64":
        raise ValueError("Finder smoke requires matching macOS ARM64 host")
    mount = Path(mount).resolve(strict=True)
    if not (mount / ".DS_Store").is_file():
        raise ValueError("Missing BB-generated Finder metadata")
    result = subprocess.run(["/usr/bin/osascript", "-s", "s", "-e", SCRIPT, str(mount)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        if "-1743" in result.stderr:
            raise RuntimeError("FINDER_AUTOMATION_DENIED")
        codes = re.findall(r"\((-?\d+)\)", result.stderr)
        raise RuntimeError("FINDER_LAYOUT_SCRIPT_FAILED " + ",".join(codes))
    try:
        values = json.loads(result.stdout.replace("{", "[").replace("}", "]"))
    except ValueError:
        raise RuntimeError("FINDER_LAYOUT_RESPONSE_INVALID") from None
    expected = {
        "icon_view": True, "bounds": None, "toolbar": False,
        "statusbar": False, "icon_size": 112, "text_size": 12,
        "background": [56797, 61166, 65535], "app_position": [140, 160],
        "applications_position": [460, 160],
    }
    if (not isinstance(values, list) or len(values) != len(expected) + 1
            or any(type(value) not in (int, float, bool) for item in values for value in (item if isinstance(item, list) else [item]))):
        raise RuntimeError("FINDER_LAYOUT_RESPONSE_INVALID")
    display = values[-1]
    if not isinstance(display, list) or len(display) != 4 or display[3] <= display[1]:
        raise RuntimeError("FINDER_LAYOUT_DISPLAY_INVALID")
    # Finder stores Cocoa coordinates; AppleScript reports top-left bounds.
    expected["bounds"] = [120, display[3] - 140 - 360, 720, display[3] - 140]
    observed = dict(zip(expected, values[:-1]))
    observed["display_bounds"] = display
    print("DMG_FINDER_OBSERVED " + json.dumps(observed, sort_keys=True), flush=True)
    failures = [name for name, value in expected.items() if observed[name] != value]
    if failures:
        raise RuntimeError("FINDER_LAYOUT_FAILED " + ",".join(failures))
    print("DMG_FINDER_LAYOUT_OK", flush=True)
    if not (mount / ".VolumeIcon.icns").is_file():
        raise ValueError("Missing BB-generated volume icon")
    bundle = mount / "Sample Desktop.app"
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    name = info["CFBundleIconFile"]
    if Path(name).name != name:
        raise ValueError("Unexpected fixture icon path")
    if not name.endswith(".icns"):
        name += ".icns"
    if (mount / ".VolumeIcon.icns").read_bytes() != (bundle / "Contents/Resources" / name).read_bytes():
        raise ValueError("Volume/reference icon bytes differ")
    icon = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", ICON_SCRIPT, str(mount), str(bundle)],
                          capture_output=True, text=True, timeout=30)
    if icon.returncode:
        raise RuntimeError("DMG_VOLUME_ICON_READ_FAILED")
    rendered = json.loads(icon.stdout)
    if set(rendered) != {"volume", "application"}:
        raise RuntimeError("DMG_VOLUME_ICON_RESPONSE_INVALID")
    for image in rendered.values():
        if (set(image) != {"width", "height", "samples"}
                or any(type(image[key]) is not int or not 1 <= image[key] <= 4096 for key in ("width", "height"))
                or len(image["samples"]) != 9
                or any(not isinstance(row, list) or len(row) != 4 or any(type(value) is not int or not 0 <= value <= 255 for value in row)
                       for row in image["samples"])):
            raise RuntimeError("DMG_VOLUME_ICON_RESPONSE_INVALID")
    print("DMG_VOLUME_ICON_OBSERVED " + json.dumps(rendered, sort_keys=True), flush=True)
    if rendered["volume"]["samples"] != rendered["application"]["samples"]:
        raise RuntimeError("DMG_VOLUME_ICON_PIXELS_MISMATCH")
    print("DMG_VOLUME_ICON_OK", flush=True)


if __name__ == "__main__":
    check_layout(sys.argv[1])
