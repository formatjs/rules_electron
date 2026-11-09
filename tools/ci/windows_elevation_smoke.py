"""Execute the BB-built elevation bridge on matching elevated Windows hosts."""

import ctypes
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import tempfile
import time


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
        result = subprocess.run([str(helper), "--wait", str(probe), str(output), *arguments], timeout=60)
        assert result.returncode == 37
        assert output.read_bytes() == "".join(value + "\0" for value in arguments).encode("utf-16-le")
        raw_options = Path(temporary) / "raw-options.bin"
        result = subprocess.run([str(helper), "--wait", str(probe), str(raw_options), "--raw-options", "/S", "--updated"], timeout=30)
        assert result.returncode == 37
        assert raw_options.read_bytes() == "--raw-options\0/S\0--updated\0".encode("utf-16-le")
        rejected = subprocess.run([str(helper), str(Path(temporary) / "missing.exe")], timeout=30)
        assert rejected.returncode == 2
        rejected = subprocess.run([str(helper)], timeout=30)
        assert rejected.returncode == 87
        detached_helper, detached_probe = Path(temporary) / "elevate.exe", Path(temporary) / "probe.exe"
        shutil.copyfile(helper, detached_helper)
        shutil.copyfile(probe, detached_probe)
        ready, release = Path(temporary) / "ready.bin", Path(temporary) / "release"
        try:
            result = subprocess.run([str(detached_helper), str(detached_probe), str(ready), "--hold", str(release)], timeout=15)
            assert result.returncode == 0
            deadline = time.monotonic() + 15
            while not ready.exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Detached elevated child did not start")
                time.sleep(0.05)
            detached_helper.unlink()
            assert not detached_helper.exists()
        finally:
            release.touch()
            deadline = time.monotonic() + 15
            while detached_probe.exists():
                try:
                    detached_probe.unlink()
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Detached elevated child did not exit")
                    time.sleep(0.05)
    print("WINDOWS_ELEVATION_BRIDGE_OK")


if __name__ == "__main__":
    main()
