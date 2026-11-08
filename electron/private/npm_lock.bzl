"""Validate lockfile inputs before repository downloads."""

def _matches(values, target):
    positives = [value for value in values if not value.startswith("!")]
    return "!" + target not in values and (not positives or target in positives or "any" in positives)

def npm_lock_packages(lock, include_dev = False, target_os = "", target_cpu = "", target_libc = ""):
    """Return selected package records or a validation error; never inspect the host."""
    if type(lock) != "dict" or lock.get("lockfileVersion") != 3 or type(lock.get("packages")) != "dict":
        return struct(packages = {}, error = "Expected npm lockfile v3 with packages")
    selected = {}
    for path, package in lock["packages"].items():
        if not path:
            continue
        if type(package) != "dict":
            return struct(packages = {}, error = "Invalid npm package record: " + path)
        if package.get("dev") and not include_dev:
            continue
        if not path.startswith("node_modules/") or any([p in ["", ".", ".."] for p in path.split("/")]) or "\\" in path or ":" in path:
            return struct(packages = {}, error = "Invalid npm package path: " + path)
        for name in path[len("node_modules/"):].split("/node_modules/"):
            parts = name.split("/")
            if not (len(parts) == 1 and not name.startswith("@") or len(parts) == 2 and parts[0].startswith("@") and len(parts[0]) > 1):
                return struct(packages = {}, error = "Invalid npm package path: " + path)
        compatible = True
        for key, target in [("os", target_os), ("cpu", target_cpu), ("libc", target_libc)]:
            values = package.get(key, [])
            if type(values) != "list" or any([type(value) != "string" for value in values]):
                return struct(packages = {}, error = "Invalid npm platform constraint: " + path)
            if values:
                if not target:
                    return struct(packages = {}, error = "Explicit target_" + key + " required: " + path)
                compatible = compatible and _matches(values, target)
        if not compatible:
            if package.get("optional"):
                continue
            return struct(packages = {}, error = "Required npm package incompatible with target: " + path)
        if package.get("hasInstallScript") or package.get("link"):
            return struct(packages = {}, error = "npm_runtime requires script-free registry packages: " + path)
        integrity, url = package.get("integrity", ""), package.get("resolved", "")
        if type(integrity) != "string" or not integrity.startswith(("sha256-", "sha384-", "sha512-")) or type(url) != "string" or not url.startswith("https://"):
            return struct(packages = {}, error = "Expected HTTPS archive with SHA-256/384/512 integrity: " + path)
        selected[path] = package
    return struct(packages = selected, error = "")
