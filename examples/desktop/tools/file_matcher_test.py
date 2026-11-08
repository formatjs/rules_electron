"""Exercise the real matcher with package-style inclusions and exclusions."""

import json
from pathlib import Path
import subprocess
import sys

node, script, modules = [str(Path(value).resolve()) for value in sys.argv[1:]]
files = ["root.node", "lib/addon.node", "lib/skip.node", "lib/library.dll", "lib/fast.so", "lib/other.so",
         "assets/public.txt", "assets/private/hidden.txt", "assets/private/keep.txt", ".hidden/addon.node",
         "image12.png", "image1.png", "main.cjs"]
cases = [
    (["**/*.{node,dll}", "!**/skip.node"],
     ["root.node", "lib/addon.node", "lib/library.dll", ".hidden/addon.node"]),
    (["assets", "!assets/private/**", "assets/private/keep.txt"],
     ["assets/public.txt", "assets/private/keep.txt"]),
    (["lib/@(fast|slow).so", "image[0-9]?.png"], ["lib/fast.so", "image12.png"]),
    (["!**/*.node"], []),
]
for patterns, expected in cases:
    result = subprocess.run([node, "--no-global-search-paths", script, modules], input=json.dumps({"files": files, "patterns": patterns}),
                            text=True, encoding="utf-8", stdout=subprocess.PIPE, check=True)
    assert json.loads(result.stdout) == expected, patterns
