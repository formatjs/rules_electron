"""Native source-built AppImage runtime extraction and execution."""

import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

RUNTIME, MKSQUASHFS, PROBE = [str(Path(value).resolve()) for value in sys.argv[1:4]]
ENV = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC"}


class AppImageRuntimeTest(unittest.TestCase):
    def test_static_pie_extract_and_run_both_codecs(self):
        original = Path(RUNTIME).read_bytes()
        raw = bytearray(original)
        self.assertEqual(raw[:6], b"\x7fELF\x02\x01")
        self.assertEqual(struct.unpack_from("<H", raw, 16)[0], 3)  # ET_DYN.
        phoff = struct.unpack_from("<Q", raw, 32)[0]
        phsize, phcount = struct.unpack_from("<HH", raw, 54)
        for index in range(phcount):
            position = phoff + index * phsize
            kind = struct.unpack_from("<I", raw, position)[0]
            self.assertNotEqual(kind, 3)  # PT_INTERP.
            if kind == 2:  # PT_DYNAMIC.
                offset = struct.unpack_from("<Q", raw, position + 8)[0]
                size = struct.unpack_from("<Q", raw, position + 32)[0]
                for cursor in range(offset, offset + size, 16):
                    self.assertNotEqual(struct.unpack_from("<Q", raw, cursor)[0], 1)  # DT_NEEDED.
        version = subprocess.run([RUNTIME, "--appimage-version"], env=ENV, check=True, capture_output=True)
        self.assertIn(b"fedfad51acc2860b2916a1eef32ba4a500ff31ef", version.stderr)
        offset = int(subprocess.check_output([RUNTIME, "--appimage-offset"], env=ENV))
        self.assertGreater(offset, 64)
        self.assertLessEqual(offset, len(raw))
        raw[8:11] = b"AI\x02"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            appdir = root / "AppDir"
            appdir.mkdir()
            shutil.copyfile(PROBE, appdir / "AppRun")
            (appdir / "AppRun").chmod(0o755)
            (appdir / "世界").write_text("payload data")
            (appdir / "alias").symlink_to("世界")
            for compressor in ("gzip", "zstd"):
                filesystem = root / (compressor + ".squashfs")
                subprocess.run([MKSQUASHFS, str(appdir), str(filesystem), "-noappend", "-no-progress",
                                "-no-xattrs", "-all-root", "-all-time", "0", "-mkfs-time", "0",
                                "-processors", "2", "-mem", "64M", "-comp", compressor], env=ENV, check=True)
                image = root / (compressor + ".AppImage")
                with image.open("wb") as output:
                    output.write(raw[:offset])
                    with filesystem.open("rb") as source:
                        shutil.copyfileobj(source, output)
                image.chmod(0o755)
                working = root / compressor
                working.mkdir()
                subprocess.run([str(image), "--appimage-extract"], cwd=working, env=ENV, check=True, capture_output=True)
                self.assertEqual((working / "squashfs-root/alias").read_text(), "payload data")
                self.assertEqual((working / "squashfs-root/AppRun").stat().st_mode & 0o777, 0o755)
                environment = dict(ENV, TMPDIR=str(working))
                launched = subprocess.check_output([str(image), "--appimage-extract-and-run", "payload-check"],
                                                  cwd=working, env=environment)
                self.assertEqual(launched, b"APPIMAGE_PAYLOAD_OK\n")
        self.assertEqual(Path(RUNTIME).read_bytes(), original)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
