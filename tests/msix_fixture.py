"""Declared minimal PE app for downstream MSIX rule acceptance tests."""

from pathlib import Path
import shutil
import sys


if __name__ == "__main__":
    binary, output = sys.argv[1:]
    app = Path(output)
    app.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, app / "helper.exe")
    (app / "payloads").mkdir()
    (app / "payloads/世界.bin").write_bytes(bytes(range(256)) * 1024 + b"tail")
    (app / "empty").write_bytes(b"")
