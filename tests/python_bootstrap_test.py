"""Python tools must start without Python installed on PATH."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PythonBootstrapTest(unittest.TestCase):
    def test_no_ambient_python_needed(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory)
            # Keep the Linux shell bootstrap tools; expose no Python executable.
            for name in ["bash", "dirname", "readlink", "which", "mkdir", "ln", "env"]:
                (tools / name).symlink_to("/usr/bin/" + name)
            result = subprocess.run([str(PROBE)], check=True, capture_output=True, text=True, env={
                "PATH": str(tools), "RUNFILES_DIR": os.environ["TEST_SRCDIR"],
                "LC_ALL": "C.UTF-8",
            })
            runtime = json.loads(result.stdout)
            self.assertEqual(runtime["version"], [3, 11])
            self.assertFalse(Path(runtime["executable"]).is_relative_to("/usr"))


if __name__ == "__main__":
    PROBE = Path(sys.argv.pop(1)).absolute()
    unittest.main()
