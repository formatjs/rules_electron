"""Relocate actual Bazel output, then execute its native packaging fixture."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


if __name__ == "__main__":
    source = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as directory:
        app = Path(directory) / "relocated app"
        shutil.copytree(source, app)
        assert (app / "resources/app/main.js").is_file()
        assert (app / "resources/app/package.json").is_file()
        assert (app / "licenses/NOTICE.txt").read_text() == "Packaging fixture notice.\n"
        assert (app / "icudtl.dat").read_bytes() == b"Packaging fixture data; not real ICU data.\n"
        result = subprocess.run([str(app / "electron")], cwd=directory, check=True, capture_output=True, text=True)
        assert result.stdout == "packaging fixture\n", result.stdout
