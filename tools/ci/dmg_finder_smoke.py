"""Read BB-generated DMG settings through the matching native Finder."""

from pathlib import Path
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
            if current view of targetWindow is not icon view then error "FINDER_LAYOUT_VIEW"
            if bounds of targetWindow is not {120, 140, 720, 500} then error "FINDER_LAYOUT_BOUNDS"
            if toolbar visible of targetWindow then error "FINDER_LAYOUT_TOOLBAR"
            if statusbar visible of targetWindow then error "FINDER_LAYOUT_STATUSBAR"
            set options to icon view options of targetWindow
            if icon size of options is not 112 then error "FINDER_LAYOUT_ICON_SIZE"
            if text size of options is not 12 then error "FINDER_LAYOUT_TEXT_SIZE"
            if background color of options is not {56797, 61166, 65535} then error "FINDER_LAYOUT_BACKGROUND"
            if position of item "Sample Desktop.app" of targetFolder is not {140, 160} then error "FINDER_LAYOUT_APP_POSITION"
            if position of item "Applications" of targetFolder is not {460, 160} then error "FINDER_LAYOUT_APPLICATIONS_POSITION"
            close targetWindow
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
    result = subprocess.run(["/usr/bin/osascript", "-e", SCRIPT, str(mount)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        if "-1743" in result.stderr:
            raise RuntimeError("FINDER_AUTOMATION_DENIED")
        markers = [name for name in ["VIEW", "BOUNDS", "TOOLBAR", "STATUSBAR", "ICON_SIZE", "TEXT_SIZE",
                                     "BACKGROUND", "APP_POSITION", "APPLICATIONS_POSITION"]
                   if "FINDER_LAYOUT_" + name in result.stderr]
        raise RuntimeError("FINDER_LAYOUT_FAILED " + ",".join(markers))
    print("DMG_FINDER_LAYOUT_OK", flush=True)


if __name__ == "__main__":
    check_layout(sys.argv[1])
