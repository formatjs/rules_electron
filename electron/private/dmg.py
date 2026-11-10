"""Package a macOS app in a reproducible, compressed HFS+ UDIF image."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

from electron.private.archive import inventory, relative
from electron.private.files import normalize
from electron.private.finder import background_alias, background_identity, write_layout
from electron.private.icons import png_dimensions, validate_icns


def create_dmg(source, app_name, volume_name, source_date_epoch, applications_link, xorriso, converter, output,
               finder_window=(), app_position=(160, 180), applications_position=(480, 180),
               icon_size=128, text_size=14, background_color="#ffffff", volume_icon="", background_image=""):
    relative(app_name)
    if "/" in app_name or not app_name.endswith(".app"):
        raise ValueError("Expected single app bundle name")
    if (not volume_name or len(volume_name.encode("utf-8")) > 32
            or any(ord(char) < 32 or char in "/\\:" for char in volume_name)):
        raise ValueError("Invalid DMG volume label")
    if type(source_date_epoch) is not int or not 0 <= source_date_epoch <= 2082758399:
        raise ValueError("DMG timestamp must fit the HFS+ date range")
    date = datetime.fromtimestamp(source_date_epoch, timezone.utc).strftime("%Y%m%d%H%M%S") + "00"
    output = Path(output)
    source = Path(source).resolve(strict=True)
    if output.resolve() == source or source.is_dir() and output.resolve().is_relative_to(source):
        raise ValueError("DMG output must be outside its input")
    for asset in (volume_icon, background_image):
        if asset and output.resolve() == Path(asset).resolve(strict=True):
            raise ValueError("DMG output must be outside its inputs")
    if background_image and not finder_window:
        raise ValueError("DMG background image requires finder_window")
    with tempfile.TemporaryDirectory(prefix="electron-dmg-", dir=output.parent) as temporary:
        root = Path(temporary)
        staging = root / "volume"
        bundle = staging / app_name
        bundle.mkdir(parents=True)
        digest = hashlib.sha256(app_name.encode("utf-8"))
        with inventory(source, "macos") as (entries, open_entry):
            if len(entries) > 200000 or sum(entry.size for entry in entries.values()) > 16 * 1024**3:
                raise ValueError("DMG input exceeds limits")
            for name, entry in sorted(entries.items()):
                digest.update(json.dumps([name, entry.kind, entry.mode, entry.size, entry.target], ensure_ascii=False).encode("utf-8") + b"\n")
                destination = bundle / name
                if entry.kind == "symlink":
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                if entry.kind == "directory":
                    destination.mkdir(exist_ok=True)
                else:
                    with open_entry(entry) as content, destination.open("wb") as target:
                        for block in iter(lambda: content.read(1024**2), b""):
                            digest.update(block)
                            target.write(block)
                destination.chmod(entry.mode)
            for name, entry in sorted(entries.items()):
                if entry.kind == "symlink":
                    destination = bundle / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.symlink_to(entry.target)
        info_path = bundle / "Contents/Info.plist"
        if not info_path.is_file() or info_path.stat().st_size > 1024**2:
            raise ValueError("Missing or oversized app Info.plist")
        info = plistlib.loads(info_path.read_bytes())
        executable = info.get("CFBundleExecutable", "") if isinstance(info, dict) else ""
        if (not isinstance(info, dict) or info.get("CFBundlePackageType") != "APPL" or not isinstance(executable, str) or not executable
                or "/" in relative(executable) or not (bundle / "Contents/MacOS" / executable).is_file()):
            raise ValueError("Invalid macOS app bundle")
        if applications_link:
            (staging / "Applications").symlink_to("/Applications")
        if volume_icon:
            icon = staging / ".VolumeIcon.icns"
            icon.write_bytes(Path(volume_icon).read_bytes())
            validate_icns(icon)
            digest.update(b".VolumeIcon.icns\0" + icon.read_bytes())
        if finder_window:
            layout = staging / ".DS_Store"
            image_alias = b""
            if background_image:
                image = staging / ".background.png"
                if Path(background_image).stat().st_size > 64 * 1024**2:
                    raise ValueError("DMG background image exceeds 64 MiB")
                image.write_bytes(Path(background_image).read_bytes())
                if max(png_dimensions(image)) > 8192:
                    raise ValueError("DMG background dimensions exceed 8192 pixels")
                digest.update(b".background.png\0" + image.read_bytes())
                image_alias = background_alias(volume_name, source_date_epoch)
            payload_digest = digest.copy()
            write_layout(layout, app_name, applications_link, finder_window, app_position,
                         applications_position, icon_size, text_size, background_color, image_alias)
            digest.update(layout.read_bytes())
        normalize(staging)
        environment = {"PATH": "", "HOME": str(root), "TMPDIR": str(root), "TZ": "UTC", "LC_ALL": "C",
                       "SOURCE_DATE_EPOCH": str(source_date_epoch)}
        iso = root / "filesystem.iso"

        def write_filesystem(identity):
            subprocess.run([xorriso, "-no_rc", "-local_charset", "UTF-8", "-as", "mkisofs", "-hfsplus", "-R",
                            "-uid", "0", "-gid", "0", "-apm-block-size", "512", "-input-charset", "UTF-8", "-output-charset", "UTF-8",
                            "-hfsplus-serial-no", identity.hexdigest()[:16], "--set_all_file_dates", date,
                            "--modification-date=" + date, "-V", volume_name,
                            *(["-hfs-bless-by", "show_folder", "/"] if finder_window else []),
                            "-o", str(iso), str(staging)],
                           env=environment, check=True, capture_output=True, timeout=1800)

        write_filesystem(digest)
        if background_image:
            identity = background_identity(iso)
            write_layout(layout, app_name, applications_link, finder_window, app_position,
                         applications_position, icon_size, text_size, background_color,
                         background_alias(volume_name, source_date_epoch, *identity))
            digest = payload_digest.copy()
            digest.update(layout.read_bytes())
            normalize(staging)
            iso.unlink()
            write_filesystem(digest)
            if background_identity(iso) != identity:
                raise ValueError("HFS+ background identity changed during layout finalization")
        image = root / "release.dmg"
        subprocess.run([converter, str(iso), str(image)], env=environment, check=True, capture_output=True, timeout=1800)
        with image.open("rb") as content:
            content.seek(-512, os.SEEK_END)
            if content.read(4) != b"koly":
                raise ValueError("Invalid converted DMG")
        image.chmod(0o644)
        os.utime(image, (0, 0))
        os.replace(image, output)


if __name__ == "__main__":
    create_dmg(**json.loads(Path(sys.argv[1]).read_text()), output=sys.argv[2])
