"""Execute the BB-built elevation bridge on matching elevated Windows hosts."""

import ctypes
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def main():
    directory, architecture = Path(sys.argv[1]), sys.argv[2]
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Elevation smoke requires elevated disposable runner")
    helper, probe = directory / "windows_elevate.exe", directory / "elevation_probe.exe"
    for path in (helper, probe):
        data = path.read_bytes()
        offset = struct.unpack_from("<I", data, 60)[0]
        machine = struct.unpack_from("<H", data, offset + 4)[0]
        assert machine == {"x64": 0x8664, "arm64": 0xaa64}[architecture]
    with tempfile.TemporaryDirectory(prefix="elevation-smoke-") as temporary:
        output = Path(temporary) / "result 世界.bin"
        arguments = ["", "two words", 'embedded"quote', "trailing\\", "space and slash\\", "世界", "\\\\server\\share\\"]
        result = subprocess.run([str(helper), str(probe), str(output), *arguments], timeout=60)
        assert result.returncode == 37
        assert output.read_bytes() == "".join(value + "\0" for value in arguments).encode("utf-16-le")
        rejected = subprocess.run([str(helper), str(Path(temporary) / "missing.exe")], timeout=30)
        assert rejected.returncode == 2
        rejected = subprocess.run([str(helper)], timeout=30)
        assert rejected.returncode == 87
    print("WINDOWS_ELEVATION_BRIDGE_OK")


if __name__ == "__main__":
    main()
