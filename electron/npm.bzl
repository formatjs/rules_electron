"""Integrity-pinned npm runtime trees without package managers or install scripts."""

load("//electron/private:npm_lock.bzl", "npm_lock_packages")

def _impl(ctx):
    selection = npm_lock_packages(
        json.decode(ctx.read(ctx.attr.lock)),
        include_dev = ctx.attr.include_dev,
        target_os = ctx.attr.target_os,
        target_cpu = ctx.attr.target_cpu,
        target_libc = ctx.attr.target_libc,
    )
    if selection.error:
        fail(selection.error)
    for path, package in selection.packages.items():
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
        "lock": attr.label(mandatory = True, allow_single_file = [".json"]),
        "include_dev": attr.bool(default = False, doc = "Include packages marked dev in the lockfile."),
        "strip_node_modules": attr.bool(default = True, doc = "Expose node_modules contents at the tree root for app mapping."),
        "target_os": attr.string(doc = "Explicit npm OS name, such as linux, darwin or win32. Required for constrained packages."),
        "target_cpu": attr.string(doc = "Explicit npm CPU name, such as x64 or arm64. Required for constrained packages."),
        "target_libc": attr.string(doc = "Explicit npm libc name, such as glibc or musl. Required for constrained packages."),
    },
    doc = "Fetch an npm lockfile v3 dependency tree. No dependency resolution, lifecycle scripts or host platform discovery.",
)
