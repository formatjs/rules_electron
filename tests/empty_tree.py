"""Emit empty leaves and ordinary payload into a declared test tree."""

from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
(root / "nested/empty").mkdir(parents=True)
(root / ".hidden/empty").mkdir(parents=True)
(root / "message.txt").write_bytes(b"tree payload\n")
Path(sys.argv[2]).write_text(json.dumps([".hidden/empty", "nested/empty"]) + "\n")
if len(sys.argv) > 3:
    Path(sys.argv[3]).write_text(json.dumps({"current": "", "nested/alias": "message.txt"}) + "\n")
