"""Validate lockfile inputs before repository downloads."""

_NUL = json.decode('"\\u0000"')

def _matches(values, target):
    positives = [value for value in values if not value.startswith("!")]
    return "!" + target not in values and (not positives or target in positives or "any" in positives)

def npm_package_path(path):
    """Validate one explicit Node installation path; return an error or empty string."""
    if type(path) != "string" or not path.startswith("node_modules/") or any([p in ["", ".", ".."] for p in path.split("/")]) or any([c in path for c in ["\\", ":", _NUL]]):
        return "Invalid npm package path: " + str(path)
    for name in path[len("node_modules/"):].split("/node_modules/"):
        parts = name.split("/")
        if not (len(parts) == 1 and not name.startswith("@") or len(parts) == 2 and parts[0].startswith("@") and len(parts[0]) > 1):
            return "Invalid npm package path: " + path
    return ""

def npm_bundle_identity(path, locked, actual):
    """Check bundled bytes against their lock identity after owner verification."""
    name = locked.get("name", path[len("node_modules/"):].split("/node_modules/")[-1])
    if type(name) != "string" or not name or type(actual) != "dict" or actual.get("name") != name or actual.get("version") != locked.get("version"):
        return "Bundled npm package identity differs from lock: " + path
    return ""

def _invalid(message):
    return struct(packages = {}, bundled = {}, omitted = [], error = message)

def _parents(path):
    parts = path.split("/node_modules/")
    return ["/node_modules/".join(parts[:length]) for length in range(1, len(parts))]

def npm_lock_packages(lock, include_dev = False, target_os = "", target_cpu = "", target_libc = ""):
    """Return selected package records or a validation error; never inspect the host."""
    if type(lock) != "dict" or lock.get("lockfileVersion") != 3 or type(lock.get("packages")) != "dict":
        return _invalid("Expected npm lockfile v3 with packages")
    if any([type(path) != "string" for path in lock["packages"]]):
        return _invalid("Invalid npm package path")
    selected, bundles, omitted = {}, {}, {}
    for path in sorted(lock["packages"]):
        package = lock["packages"][path]
        if not path:
            continue
        if type(package) != "dict":
            return _invalid("Invalid npm package record: " + path)
        if package.get("dev") and not include_dev or any([parent in omitted for parent in _parents(path)]):
            omitted[path] = True
            continue
        error = npm_package_path(path)
        if error:
            return _invalid(error)
        compatible = True
        for key, target in [("os", target_os), ("cpu", target_cpu), ("libc", target_libc)]:
            values = package.get(key, [])
            if type(values) != "list" or any([type(value) != "string" for value in values]):
                return _invalid("Invalid npm platform constraint: " + path)
            if values:
                if not target:
                    return _invalid("Explicit target_" + key + " required: " + path)
                compatible = compatible and _matches(values, target)
        if not compatible:
            if package.get("optional"):
                omitted[path] = True
                continue
            return _invalid("Required npm package incompatible with target: " + path)
        if package.get("hasInstallScript") or package.get("link"):
            return _invalid("npm_runtime requires script-free registry packages: " + path)
        if package.get("inBundle"):
            if type(package["inBundle"]) != "bool" or type(package.get("version")) != "string" or not package["version"]:
                return _invalid("Bundled npm package requires an exact version: " + path)
            bundles[path] = package
            continue
        integrity, url = package.get("integrity", ""), package.get("resolved", "")
        if type(integrity) != "string" or not integrity.startswith(("sha256-", "sha384-", "sha512-")) or type(url) != "string" or not url.startswith("https://"):
            return _invalid("Expected HTTPS archive with SHA-256/384/512 integrity: " + path)
        selected[path] = package
    bundled = {}
    for path, package in bundles.items():
        owners = [parent for parent in _parents(path) if parent in selected]
        if not owners:
            return _invalid("Bundled npm package requires a pinned archive owner: " + path)
        owner = owners[-1]
        bundled[path] = struct(owner = owner, package = package)
    return struct(packages = selected, bundled = bundled, omitted = sorted(omitted), error = "")
