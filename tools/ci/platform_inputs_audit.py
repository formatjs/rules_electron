"""Check platform-specific example inputs against Bazel's actual actions."""

import json
from pathlib import Path
import sys


def audit(graph, workspace):
    targets = {item["id"]: item["label"] for item in graph.get("targets", [])}
    fragments = {item["id"]: item["label"] for item in graph.get("pathFragments", [])}
    names = {item["id"]: fragments[item["pathFragmentId"]] for item in graph.get("artifacts", [])}
    sets = {item["id"]: item for item in graph.get("depSetOfFiles", [])}
    counts = {"linux": 0, "macos": 0, "windows": 0}

    def includes_mac_script(action):
        pending, visited = list(action.get("inputDepSetIds", [])), set()
        while pending:
            identifier = pending.pop()
            if identifier in visited:
                continue
            visited.add(identifier)
            entry = sets[identifier]
            if any(names[value] == "macos-update-smoke.cjs" for value in entry.get("directArtifactIds", [])):
                return True
            pending.extend(entry.get("transitiveDepSetIds", []))
        return False

    for action in graph.get("actions", []):
        if action.get("mnemonic") != "ElectronApp":
            continue
        label = targets[action["targetId"]]
        if not label.endswith("_assembled"):
            continue
        manifests = [value for value in action.get("arguments", []) if value.endswith(".manifest.json")]
        if len(manifests) != 1:
            raise ValueError("Expected one assembly manifest")
        manifest = json.loads((workspace / manifests[0]).read_text())
        platform = manifest["platform"]
        if platform not in counts:
            raise ValueError("Unexpected assembly platform")
        packaged = any(entry["path"].endswith("/app/macos-update-smoke.cjs") for entry in manifest["entries"])
        required = platform == "macos"
        if (packaged, includes_mac_script(action)) != (required, required):
            raise ValueError(f"macOS-only smoke input leaked or missing: {label} ({platform})")
        counts[platform] += 1
    if not all(counts.values()):
        raise ValueError("Expected Linux, macOS and Windows assembly actions")
    return counts


if __name__ == "__main__":
    print("PLATFORM_INPUTS_AUDIT_OK " + json.dumps(audit(json.loads(Path(sys.argv[1]).read_text()), Path.cwd()), sort_keys=True))
