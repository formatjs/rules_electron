"""Lock selection respects production and explicit target inputs."""

load("//electron/private:npm_lock.bzl", "npm_lock_packages", "npm_package_path")

_PACKAGE = {"resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz", "integrity": "sha512-declared"}

def _lock(packages):
    return {"lockfileVersion": 3, "packages": dict({"": {"name": "app"}}, **packages)}

def _impl(_ctx):
    errors = []
    for path in ["node_modules/a", "node_modules/@example/a", "node_modules/a/node_modules/@other/b"]:
        if npm_package_path(path):
            errors.append("Valid installation path rejected: " + path)
    for path in ["a", "node_modules/../a", "node_modules/@scope", "node_modules/a/child", "node_modules/a//b", "node_modules/a\\b"]:
        if not npm_package_path(path):
            errors.append("Unsafe installation path accepted: " + path)
    records = {
        "node_modules/example": _PACKAGE,
        "node_modules/@example/nested/node_modules/child": _PACKAGE,
        "node_modules/dev-only": dict(_PACKAGE, dev = True),
        "node_modules/shared-optional": dict(_PACKAGE, devOptional = True),
        "node_modules/arm-only": dict(_PACKAGE, optional = True, os = ["linux"], cpu = ["arm64"]),
    }
    result = npm_lock_packages(_lock(records), target_os = "linux", target_cpu = "x64")
    expected = ["node_modules/example", "node_modules/@example/nested/node_modules/child", "node_modules/shared-optional"]
    if result.error or sorted(result.packages) != sorted(expected):
        errors.append("Production/x64 selection: " + result.error)
    result = npm_lock_packages(_lock(records), include_dev = True, target_os = "linux", target_cpu = "arm64")
    if result.error or sorted(result.packages) != sorted(records):
        errors.append("Development/ARM64 selection: " + result.error)
    result = npm_lock_packages(_lock({"node_modules/example": dict(_PACKAGE, os = ["!win32"])}), target_os = "darwin")
    if result.error or "node_modules/example" not in result.packages:
        errors.append("Negated OS constraint rejected compatible target")
    invalid = [
        ({"lockfileVersion": 2, "packages": {}}, "lockfile v3"),
        (_lock({"node_modules/../escape": _PACKAGE}), "package path"),
        (_lock({"node_modules/example/arbitrary": _PACKAGE}), "package path"),
        (_lock({"node_modules/example": dict(_PACKAGE, hasInstallScript = True)}), "script-free"),
        (_lock({"node_modules/example": dict(_PACKAGE, link = True)}), "script-free"),
        (_lock({"node_modules/example": dict(_PACKAGE, integrity = "sha1-weak")}), "integrity"),
        (_lock({"node_modules/example": dict(_PACKAGE, resolved = "file:///tmp/package")}), "HTTPS"),
        (_lock({"node_modules/example": dict(_PACKAGE, os = ["linux"])}), "target_os"),
        (_lock({"node_modules/example": dict(_PACKAGE, os = ["!linux"])}), "incompatible"),
    ]
    for lock, message in invalid:
        # Missing target is intentional except for the incompatibility case.
        result = npm_lock_packages(lock, target_os = "linux" if message == "incompatible" else "")
        if message not in result.error or result.packages:
            errors.append("Expected rejection: " + message)
    return [AnalysisTestResultInfo(success = not errors, message = "\n".join(errors))]

npm_lock_test = rule(implementation = _impl, analysis_test = True, test = True)
