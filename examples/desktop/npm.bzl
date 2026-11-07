"""Example-only adapter for pinned, script-free npm runtime dependencies."""

def _impl(ctx):
    lock = json.decode(ctx.read(ctx.attr.lock))
    if lock.get("lockfileVersion") != 3:
        fail("Expected npm lockfile v3")
    for path, package in lock["packages"].items():
        if not path:
            continue
        if not path.startswith("node_modules/") or any([p in ["", ".", ".."] for p in path.split("/")]) or "\\" in path or ":" in path:
            fail("Invalid npm package path: %s" % path)
        if package.get("hasInstallScript") or package.get("link"):
            fail("Example npm adapter requires script-free registry packages: %s" % path)
        if not package.get("integrity") or not package.get("resolved", "").startswith("https://registry.npmjs.org/"):
            fail("Expected integrity-pinned npm registry package: %s" % path)
        ctx.download_and_extract(
            url = package["resolved"],
            integrity = package["integrity"],
            output = path,
            stripPrefix = "package",
        )
    ctx.file("BUILD.bazel", """load("@bazel_lib//lib:copy_to_directory.bzl", "copy_to_directory")
copy_to_directory(
    name = "runtime",
    srcs = glob(["node_modules/**"], exclude = ["**/BUILD", "**/BUILD.bazel"]),
    root_paths = %s,
    include_external_repositories = ["*"],
    visibility = ["//visibility:public"],
)
""" % repr(["node_modules"] if ctx.attr.strip_node_modules else ["."]))

npm_runtime = repository_rule(
    implementation = _impl,
    attrs = {
        "lock": attr.label(mandatory = True, allow_single_file = True),
        "strip_node_modules": attr.bool(default = True),
    },
)
