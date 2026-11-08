"""Select declared paths using the declared execution matcher."""

import json
import os
import subprocess


def select_files(files, patterns, tool):
    if not patterns:
        return set()
    if not tool:
        raise ValueError("File patterns require file_matcher")
    declared = set(files)
    environment = dict(os.environ)
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    result = subprocess.run([tool["node"], "--no-global-search-paths", tool["script"], tool["modules"]],
                            input=json.dumps({"files": sorted(declared), "patterns": patterns}),
                            text=True, encoding="utf-8", stdout=subprocess.PIPE, check=True, env=environment)
    selected = json.loads(result.stdout)
    if (not isinstance(selected, list) or any(not isinstance(path, str) for path in selected)
            or len(selected) != len(set(selected)) or not set(selected) <= declared):
        raise ValueError("File matcher returned undeclared or duplicate paths")
    return set(selected)
