from pathlib import Path
import sys

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
for index in range(1000):
    (root / ("resource-" + "long-name-" * 10 + str(index) + ".txt")).write_bytes(b"x")
