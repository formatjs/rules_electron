"""Real source-built SquashFS packing, extraction and reproducibility."""

import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

MKSQUASHFS, UNSQUASHFS = [str(Path(value).resolve()) for value in sys.argv[1:3]]
ENV = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC"}


def run(*arguments):
    subprocess.run(arguments, env=ENV, check=True)


class SquashfsToolsTest(unittest.TestCase):
    def test_declared_tools_roundtrip_modes_links_and_fixed_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "data/empty").mkdir(parents=True)
            (source / "data/世界").write_bytes(b"file bytes" * 1000)
            (source / "program").write_bytes(b"executable bytes")
            (source / "program").chmod(0o755)
            (source / "alias").symlink_to("data", target_is_directory=True)
            for compressor in ("gzip", "zstd"):
                outputs = []
                for index in (1, 2):
                    relocated = root / (compressor + str(index))
                    shutil.copytree(source, relocated, symlinks=True)
                    for path in relocated.rglob("*"):
                        os.utime(path, (123456789 * index, 123456789 * index), follow_symlinks=False)
                    image = root / (compressor + str(index) + ".squashfs")
                    run(MKSQUASHFS, str(relocated), str(image), "-noappend", "-no-progress", "-no-xattrs",
                        "-all-root", "-all-time", "0", "-mkfs-time", "0", "-processors", "2", "-mem", "64M", "-comp", compressor)
                    outputs.append(image)
                self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
                data = outputs[0].read_bytes()
                self.assertEqual(data[:4], b"hsqs")
                self.assertEqual(struct.unpack_from("<I", data, 8)[0], 0)
                extracted = root / (compressor + "-extracted")
                run(UNSQUASHFS, "-no-progress", "-no-xattrs", "-d", str(extracted), str(outputs[0]))
                self.assertEqual((extracted / "alias/世界").read_bytes(), b"file bytes" * 1000)
                self.assertEqual(os.readlink(extracted / "alias"), "data")
                self.assertEqual((extracted / "program").stat().st_mode & 0o777, 0o755)
                self.assertTrue((extracted / "data/empty").is_dir())
            self.assertEqual((source / "program").read_bytes(), b"executable bytes")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
