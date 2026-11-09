"""Source-built image writer emits HFS+ partitions and preserves payloads."""

import os
from pathlib import Path
import struct
import subprocess
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
            subprocess.run([TOOL, "-no_rc", "-local_charset", "UTF-8", "-as", "mkisofs", "-hfsplus", "-R", "-uid", "0", "-gid", "0", "-apm-block-size", "512",
                            "-input-charset", "UTF-8", "-output-charset", "UTF-8",
                            "-V", "Example", "--modification-date=2020010100000000", "-o", str(image), str(source)],
                           env=environment, check=True, capture_output=True, timeout=60)
            data = image.read_bytes()
            self.assertEqual(data[512:514], b"PM")
            count = struct.unpack_from(">I", data, 516)[0]
            self.assertLess(count, 64)
            partitions = [data[index * 512:(index + 1) * 512] for index in range(1, count + 1)]
            hfs = [entry for entry in partitions if entry[48:80].rstrip(b"\0") == b"Apple_HFS"]
            self.assertEqual(len(hfs), 1)
            start = struct.unpack_from(">I", hfs[0], 8)[0] * 512
            self.assertEqual(data[start + 1024:start + 1026], b"H+")
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
