"""Declared execution tools for archive-relative file selection."""

ElectronFileMatcherInfo = provider(fields = {
    "node": "Execution Node FilesToRunProvider.",
    "modules": "Dependency root or linked minimatch package directory.",
    "script": "File selection script.",
})

def _impl(ctx):
    modules = ctx.attr.modules[DefaultInfo].files.to_list()
    if len(modules) != 1 or not modules[0].is_directory:
        fail("modules must provide one dependency root or linked npm package directory")
    runfiles = ctx.attr.modules[DefaultInfo].default_runfiles
    for target in ctx.attr.data:
        runfiles = runfiles.merge(target[DefaultInfo].default_runfiles).merge(ctx.runfiles(transitive_files = target[DefaultInfo].files))
    return [
        ElectronFileMatcherInfo(node = ctx.attr.node[DefaultInfo].files_to_run, modules = modules[0], script = ctx.file._script),
        DefaultInfo(
            files = depset([modules[0], ctx.file._script], transitive = [ctx.attr.node[DefaultInfo].files, runfiles.files]),
            runfiles = runfiles.merge(ctx.runfiles(files = [modules[0], ctx.file._script])).merge(ctx.attr.node[DefaultInfo].default_runfiles),
        ),
        OutputGroupInfo(node = depset([ctx.executable.node])),
    ]

electron_file_matcher = rule(
    implementation = _impl,
    attrs = {
        "node": attr.label(mandatory = True, executable = True, cfg = "exec"),
        "data": attr.label_list(cfg = "exec", doc = "Additional declared npm dependency closures, including linked-package runfiles."),
        "modules": attr.label(mandatory = True, cfg = "exec"),
        "_script": attr.label(default = Label("//electron/private:file_matcher.cjs"), allow_single_file = True),
    },
    doc = "Adapt declared Node and pinned minimatch modules for file selection; no package installation during actions.",
)
