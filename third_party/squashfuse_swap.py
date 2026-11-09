"""Generate Squashfuse swap includes from pinned upstream structure definitions."""

import hashlib
from pathlib import Path
import re
import sys


def generate(header, upstream, declarations, definitions):
    if hashlib.sha256(Path(upstream).read_bytes()).hexdigest() != "4fcbfc9585cf747e55dddbf9246426470d660c50c0d5a90634d94268cc20c794":
        raise ValueError("Upstream Squashfuse swap generator changed")
    functions, prototypes = [], []
    active = False
    for line in Path(header).read_text().splitlines():
        match = re.match(r"^struct (squashfs_(\S+))", line)
        if match:
            if active:
                raise ValueError("Nested Squashfuse structure")
            active = True
            signature = f"void sqfs_swapin_{match[2]}(struct {match[1]} *s)"
            functions.append(signature + "{")
            prototypes.append(signature + ";")
        elif active and line.startswith("}"):
            functions.append("}")
            active = False
        elif active:
            field = re.fullmatch(r"\s*__le(\d+)\s*([a-z_]*);", line)
            if field:
                if field[1] not in ("16", "32", "64"):
                    raise ValueError("Unsupported Squashfuse field width")
                functions.append(f"sqfs_swapin{field[1]}_internal(&s->{field[2]});")
    if active or not prototypes:
        raise ValueError("Incomplete Squashfuse structures")
    Path(declarations).write_text("\n".join(prototypes) + "\n")
    Path(definitions).write_text("\n".join(functions) + "\n")


if __name__ == "__main__":
    generate(*sys.argv[1:])
