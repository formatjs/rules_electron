"""Native source-built AppImage runtime extraction and execution."""

import os
import json
import base64
import hashlib
import zlib
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from electron.private.appimage import append_blockmap, create_appimage, elf_prefix
from electron.private.archive import create_archive
from electron.private.update import create_feed, embedded_blockmap_size

RUNTIME, MKSQUASHFS, PROBE, LAUNCHER, ICON = [str(Path(value).resolve()) for value in sys.argv[1:6]]
ENV = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC"}


class AppImageRuntimeTest(unittest.TestCase):
    def test_rejects_wrong_cpu_truncated_and_dynamic_runtime(self):
        original = Path(RUNTIME).read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "runtime"
            mutations = []
            wrong_cpu = bytearray(original)
            struct.pack_into("<H", wrong_cpu, 18, 183)
            mutations.append(wrong_cpu)
            mutations.append(original[:64])
            interpreter = bytearray(original)
            phoff = struct.unpack_from("<Q", interpreter, 32)[0]
            struct.pack_into("<I", interpreter, phoff, 3)
            mutations.append(interpreter)
            for content in mutations:
                candidate.write_bytes(content)
                with self.assertRaises(ValueError):
                    elf_prefix(candidate, "x64", runtime=True)

    def test_rejects_corrupt_blockmap_trailer_stream_and_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "sample.AppImage"
            image.write_bytes(b"payload bytes")
            append_blockmap(image)
            original = image.read_bytes()
            size = embedded_blockmap_size(image)
            body = original[:-size - 4]
            blockmap = json.loads(zlib.decompress(original[-size - 4:-4], wbits=-15))
            blockmap["files"][0]["sizes"][0] += 1
            compressor = zlib.compressobj(wbits=-15)
            compressed = compressor.compress(json.dumps(blockmap).encode()) + compressor.flush()
            cases = [original[:-4] + struct.pack(">I", len(original) + 1),
                     body + compressed + struct.pack(">I", len(compressed)),
                     original[:-4] + b"junk" + struct.pack(">I", size + 4)]
            for invalid in cases:
                image.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    embedded_blockmap_size(image)

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
            shutil.copyfile(PROBE, appdir / "sample")
            (appdir / "sample").chmod(0o755)
            (appdir / "世界").write_text("payload data")
            (appdir / "alias").symlink_to("世界")
            (appdir / "empty").mkdir()
            directories = root / "directories.json"
            directories.write_text(json.dumps(["tracked/nested-empty"]))
            for compressor in ("gzip", "zstd"):
                image = root / (compressor + ".AppImage")
                arguments = dict(runtime=RUNTIME, launcher=LAUNCHER, mksquashfs=MKSQUASHFS,
                                 app_id="org.example.appimage", product_name="Sample App",
                                 executable_name="sample", architecture="x64", icon=ICON,
                                 directory_manifest=str(directories), compressor=compressor, protocols=["example"], file_associations=["application/x-example"])
                create_appimage(app=str(appdir), output=str(image), **arguments)
                relocated = root / (compressor + "-relocated")
                shutil.copytree(appdir, relocated, symlinks=True)
                for path in relocated.rglob("*"):
                    os.utime(path, (12345678, 12345678), follow_symlinks=False)
                archive = root / (compressor + "-import.zip")
                create_archive(relocated, "linux", "Application", "zip", 9, archive, directory_manifest=str(directories))
                second = root / (compressor + "-second.AppImage")
                create_appimage(app=str(archive), output=str(second), **arguments)
                self.assertEqual(image.read_bytes(), second.read_bytes())
                self.assertEqual(image.read_bytes()[8:11], b"AI\x02")
                self.assertEqual(int(subprocess.check_output([str(image), "--appimage-offset"], env=ENV)), offset)
                map_size = embedded_blockmap_size(image)
                data = image.read_bytes()
                blockmap = json.loads(zlib.decompress(data[-map_size - 4:-4], wbits=-15))
                cursor = 0
                for size, checksum in zip(blockmap["files"][0]["sizes"], blockmap["files"][0]["checksums"]):
                    self.assertEqual(base64.b64encode(hashlib.sha256(data[cursor:cursor + size]).digest()).decode(), checksum)
                    cursor += size
                self.assertEqual(cursor, len(data) - map_size - 4)
                package = root / "package.json"
                package.write_text('{"version":"1.0.0"}')
                feed = create_feed([dict(source=str(image), name=image.name)], package, root / (compressor + "-feed"),
                                   "linux", "x64", "2026-01-01T00:00:00Z", embedded_blockmaps=[image.name])
                self.assertEqual(feed["files"][0]["blockMapSize"], map_size)
                image.chmod(0o755)
                working = root / compressor
                working.mkdir()
                subprocess.run([str(image), "--appimage-extract"], cwd=working, env=ENV, check=True, capture_output=True)
                self.assertEqual((working / "squashfs-root/alias").read_text(), "payload data")
                self.assertEqual((working / "squashfs-root/sample").stat().st_mode & 0o777, 0o755)
                environment = dict(ENV, TMPDIR=str(working))
                launched = subprocess.check_output([str(image), "--appimage-extract-and-run", "payload-check"],
                                                  cwd=working, env=environment)
                self.assertEqual(launched, b"APPIMAGE_PAYLOAD_OK\n")
                desktop = (working / "squashfs-root/org.example.appimage.desktop").read_text()
                self.assertIn("Exec=sample %U", desktop)
                self.assertIn("x-scheme-handler/example;application/x-example;", desktop)
                self.assertEqual(os.readlink(working / "squashfs-root/.DirIcon"), "org.example.appimage.svg")
                self.assertTrue((working / "squashfs-root/empty").is_dir())
                self.assertTrue((working / "squashfs-root/tracked/nested-empty").is_dir())
                installed = subprocess.check_output([str(image), "--appimage-extract-and-run", "wrong-arguments"],
                                                    env=dict(environment, APPIMAGE_EXIT_AFTER_INSTALL="true"))
                self.assertEqual(installed, b"")
        self.assertEqual(Path(RUNTIME).read_bytes(), original)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
