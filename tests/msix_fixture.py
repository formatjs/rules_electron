"""BB-only minimal PE package for native Windows Packaging API acceptance."""

from pathlib import Path
import shutil
import sys
import tempfile

from electron.private.msix import create_msix


if __name__ == "__main__":
    binary, package, logo_44, logo_150, store_logo, architecture, output = sys.argv[1:]
    with tempfile.TemporaryDirectory() as temporary:
        app = Path(temporary)
        shutil.copyfile(binary, app / "helper.exe")
        (app / "payloads").mkdir()
        (app / "payloads/世界.bin").write_bytes(bytes(range(256)) * 1024 + b"tail")
        (app / "empty").write_bytes(b"")
        create_msix(str(app), package, output, "org.example.MsixProbe", "CN=Example",
                    "Example", "MSIX Probe", "helper.exe", architecture, logo_44,
                    logo_150, store_logo, build_version="1.0.0.7")
