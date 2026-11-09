"""Immutable Electron registry inputs, exposed without evaluating their BUILD files."""

def _impl(ctx):
    pin = json.decode(ctx.read(ctx.attr.pin))
    for key, length in [("commit", 40), ("sha256", 64)]:
        value = pin[key]
        if len(value) != length or any([value[i] not in "0123456789abcdef" for i in range(len(value))]):
            fail("Invalid Electron source pin")
    ctx.download_and_extract(
        url = "https://github.com/formatjs/electron/archive/" + pin["commit"] + ".tar.gz",
        sha256 = pin["sha256"],
        stripPrefix = "electron-" + pin["commit"],
    )

    # Preserve registry BUILD bytes as data; the staging tool restores them.
    build_files = {}
    files = [".bazelversion", "tools/stage_bcr_entry.py", "registry_build_files.json"]
    pending = ["bcr", "tools"]
    root = str(ctx.path(".").realpath) + "/"
    for _ in range(20000):
        if not pending:
            break
        directory = pending.pop()
        for entry in ctx.path(directory).readdir():
            path = directory + "/" + entry.basename
            if not str(entry.realpath).startswith(root):
                fail("Electron registry input escapes source archive")
            if entry.is_dir:
                pending.append(path)
            elif entry.basename in ["BUILD", "BUILD.bazel"]:
                if path.startswith("bcr/"):
                    build_files[path] = ctx.read(entry)
                ctx.delete(entry)
            elif path.startswith("bcr/"):
                files.append(path)
    if pending:
        fail("Electron registry input traversal exceeds limit")
    ctx.file("registry_build_files.json", json.encode(build_files), executable = False)
    ctx.file("BUILD.bazel", 'filegroup(name = "registry_sources", srcs = ' + json.encode(sorted(files)) + ', visibility = ["//visibility:public"])\n')

electron_source_overlay = repository_rule(
    implementation = _impl,
    attrs = {"pin": attr.label(default = Label("//tools/ci:electron_source_pin.json"), allow_single_file = True)},
)
