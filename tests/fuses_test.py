from pathlib import Path
import tempfile
import unittest

from electron.private.fuses import SENTINEL, set_fuses


class FusesTest(unittest.TestCase):
    def test_changes_only_requested_fuses(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "electron"
            binary.write_bytes(b"prefix" + SENTINEL + b"\x01\x0811111011suffix")
            set_fuses(binary, {"runAsNode": "off", "onlyLoadAppFromAsar": "on"})
            self.assertEqual(binary.read_bytes(), b"prefix" + SENTINEL + b"\x01\x0801111111suffix")

    def test_invalid_wires_fail_without_modifying_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "electron"
            for wire in [
                b"not electron",
                SENTINEL + b"\x02\x0811111111",
                SENTINEL + b"\x01\x0811",
                SENTINEL + b"\x01\x011",
                SENTINEL + b"\x01\x0811111r11",
                SENTINEL + b"\x01\x0811111111" + SENTINEL,
            ]:
                binary.write_bytes(wire)
                with self.subTest(wire=wire), self.assertRaises(ValueError):
                    set_fuses(binary, {"runAsNode": "off", "onlyLoadAppFromAsar": "on"})
                self.assertEqual(binary.read_bytes(), wire)


if __name__ == "__main__":
    unittest.main()
