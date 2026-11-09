"""Read BB-generated DMG settings through the matching native Finder."""

import json
from pathlib import Path
import re
import platform
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
            set snapshot to {(current view of targetWindow is icon view), bounds of targetWindow, toolbar visible of targetWindow, statusbar visible of targetWindow, icon size of viewSettings, text size of viewSettings, background color of viewSettings, position of item "Sample Desktop.app" of targetFolder, position of item "Applications" of targetFolder}
            close targetWindow
            return snapshot
        on error messageText number messageNumber
            if targetWindow is not missing value then close targetWindow
            error messageText number messageNumber
        end try
    end tell
end run
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
        "icon_view": True, "bounds": [120, 140, 720, 500], "toolbar": False,
        "statusbar": False, "icon_size": 112, "text_size": 12,
        "background": [56797, 61166, 65535], "app_position": [140, 160],
        "applications_position": [460, 160],
    }
    if (not isinstance(values, list) or len(values) != len(expected)
            or any(type(value) not in (int, float, bool) for item in values for value in (item if isinstance(item, list) else [item]))):
        raise RuntimeError("FINDER_LAYOUT_RESPONSE_INVALID")
    observed = dict(zip(expected, values))
    print("DMG_FINDER_OBSERVED " + json.dumps(observed, sort_keys=True), flush=True)
    failures = [name for name, value in expected.items() if observed[name] != value]
    if failures:
        raise RuntimeError("FINDER_LAYOUT_FAILED " + ",".join(failures))
    print("DMG_FINDER_LAYOUT_OK", flush=True)


if __name__ == "__main__":
    check_layout(sys.argv[1])
