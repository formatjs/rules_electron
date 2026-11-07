import json
from pathlib import Path
import sys

from electron.private.assemble import assemble


if __name__ == "__main__":
    manifest = json.loads(Path(sys.argv[1]).read_text())
    assemble(output=sys.argv[2], **manifest)
