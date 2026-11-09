"""Source-built image writer emits HFS+ partitions and preserves payloads."""

import os
from pathlib import Path
import struct
import stat
import subprocess
import shutil
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())


class XorrisoTest(unittest.TestCase):
    def test_hfsplus_partition_and_rock_ridge_payload_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "payload"
            (source / "Sample Desktop.app/Contents/MacOS").mkdir(parents=True)
            executable = source / "Sample Desktop.app/Contents/MacOS/sample"
            executable.write_bytes(b"executable fixture\n")
            executable.chmod(0o755)
            (source / "Sample Desktop.app/Contents/empty").mkdir()
            document_name = "A document name longer than thirty one characters 世界.txt"
            (source / "Sample Desktop.app/Contents" / document_name).write_bytes(b"UTF-8 payload\n")
            (source / "Applications").symlink_to("/Applications")
            (source / "Sample Desktop.app/Contents/current").symlink_to("MacOS")
            image = root / "image.iso"
            environment = {"PATH": "", "HOME": str(root), "TZ": "UTC", "LC_ALL": "C",
                           "SOURCE_DATE_EPOCH": "1577836800"}
            def create_image(payload, output):
                subprocess.run([TOOL, "-no_rc", "-local_charset", "UTF-8", "-as", "mkisofs", "-hfsplus", "-R", "-uid", "0", "-gid", "0", "-apm-block-size", "512",
                                "-input-charset", "UTF-8", "-output-charset", "UTF-8", "-hfsplus-serial-no", "0011223344556677",
                                "--set_all_file_dates", "2020010100000000", "-V", "Example", "--modification-date=2020010100000000", "-o", str(output), str(payload)],
                               env=environment, check=True, capture_output=True, timeout=60)
            create_image(source, image)
            data = image.read_bytes()
            relocated = root / "different parent/payload"
            shutil.copytree(source, relocated, symlinks=True)
            for path in [relocated, *relocated.rglob("*")]:
                os.utime(path, (1234567890, 1234567890), follow_symlinks=False)
            second = root / "second.iso"
            create_image(relocated, second)
            self.assertEqual(data, second.read_bytes())
            self.assertEqual(data[512:514], b"PM")
            count = struct.unpack_from(">I", data, 516)[0]
            self.assertLess(count, 64)
            partitions = [data[index * 512:(index + 1) * 512] for index in range(1, count + 1)]
            hfs = [entry for entry in partitions if entry[48:80].rstrip(b"\0") == b"Apple_HFS"]
            self.assertEqual(len(hfs), 1)
            start = struct.unpack_from(">I", hfs[0], 8)[0] * 512
            self.assertEqual(data[start + 1024:start + 1026], b"H+")
            block_size = struct.unpack_from(">I", data, start + 1024 + 40)[0]
            catalog_block = struct.unpack_from(">I", data, start + 1024 + 288)[0]
            catalog = start + catalog_block * block_size
            node_size = struct.unpack_from(">H", data, catalog + 32)[0]
            leaf = struct.unpack_from(">I", data, catalog + 24)[0]
            regular_files = 0
            visited = set()
            while leaf:
                self.assertNotIn(leaf, visited)
                visited.add(leaf)
                node = data[catalog + leaf * node_size:catalog + (leaf + 1) * node_size]
                self.assertEqual(struct.unpack_from(">b", node, 8)[0], -1)
                for index in range(struct.unpack_from(">H", node, 10)[0]):
                    offset = struct.unpack_from(">H", node, node_size - 2 * (index + 1))[0]
                    record = offset + 2 + struct.unpack_from(">H", node, offset)[0]
                    if struct.unpack_from(">H", node, record)[0] != 2:
                        continue
                    if stat.S_ISREG(struct.unpack_from(">H", node, record + 42)[0]):
                        regular_files += 1
                        self.assertEqual(node[record + 48:record + 80], bytes(32))
                leaf = struct.unpack_from(">I", node, 0)[0]
            self.assertGreaterEqual(regular_files, 2)
            extracted = root / "extracted"
            subprocess.run([TOOL, "-no_rc", "-local_charset", "UTF-8", "-osirrox", "on", "-indev", str(image), "-extract", "/", str(extracted)],
                           env=environment, check=True, capture_output=True, timeout=60)
            app = extracted / "Sample Desktop.app/Contents"
            self.assertEqual((app / "MacOS/sample").read_bytes(), executable.read_bytes())
            self.assertEqual((app / "MacOS/sample").stat().st_mode & 0o777, 0o755)
            self.assertEqual(list((app / "empty").iterdir()), [])
            self.assertEqual((app / document_name).read_bytes(), b"UTF-8 payload\n")
            self.assertEqual(os.readlink(extracted / "Applications"), "/Applications")
            self.assertEqual(os.readlink(app / "current"), "MacOS")


if __name__ == "__main__":
    unittest.main()
