"""Report duplicate definitions using pinned public names only."""

import re

REPOSITORIES = (
    "electron_platform_sources", "electron_ui_sources", "electron_gfx_sources",
    "electron_base_sources", "electron_embedder_sources", "electron_libnode_sources",
    "electron_network_sources", "electron_mojo_sources", "electron_events_sources",
    "electron_display_sources", "electron_fonts_sources", "electron_skia_sources",
    "electron_partition_alloc_sources", "electron_v8_engine_sources",
)


def duplicate_definitions(log, public_files, public_targets, public_identifiers):
    log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log)
    blocks = re.split(r"(?:ld\.lld|lld-link): error: duplicate symbol: ", log)[1:13]
    result = []
    for block in blocks:
        identifiers = list(dict.fromkeys(word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", block.splitlines()[0])
                                         if word in public_identifiers))[:24]
        definitions = []
        for line in block.splitlines():
            if not line.lstrip().startswith(">>> defined at"):
                continue
            for path, number in re.findall(r"([A-Za-z0-9_./+\\-]+\.(?:cc|cpp|c|h|mm|rs)):(\d{1,7})", line):
                parts = path.replace("\\", "/").split("/")
                matches = ["/".join(parts[index:]) for index in range(len(parts))
                           if "/".join(parts[index:]) in public_files]
                if matches:
                    site = {"file": max(matches, key=len), "line": int(number)}
                    if site not in definitions:
                        definitions.append(site)
        owners = []
        for match in re.finditer(r"([A-Za-z0-9_+./-]*lib(target_[0-9a-f]{16})(?:_c|_asm)?\.(?:a|lo))", block):
            path, target = match.groups()
            if target not in public_targets:
                continue
            owner = {"target": public_targets[target]}
            for repository in REPOSITORIES:
                if "+" + repository + "/" in path or "/" + repository + "/" in path:
                    owner["repository"] = repository
                    break
            if owner not in owners:
                owners.append(owner)
        if identifiers or definitions or owners:
            result.append({"identifiers": identifiers, "definitions": definitions[:4], "owners": owners[:4]})
    return result
