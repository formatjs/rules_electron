"""Declared execution tools for Windows resource editing."""

ElectronWindowsResourceToolInfo = provider(
    doc = "Execution Node and pinned module closure for PE resources.",
    fields = {
        "node": "Execution-platform Node FilesToRunProvider.",
        "modules": "Dependency root or linked resedit package directory.",
        "script": "Resource editor script.",
    },
)

def _impl(ctx):
    modules = ctx.attr.modules[DefaultInfo].files.to_list()
    if len(modules) != 1 or not modules[0].is_directory:
        fail("modules must provide one dependency root or linked npm package directory")
    runfiles = ctx.attr.modules[DefaultInfo].default_runfiles
    for target in ctx.attr.data:
        runfiles = runfiles.merge(target[DefaultInfo].default_runfiles).merge(ctx.runfiles(transitive_files = target[DefaultInfo].files))
    return [
        ElectronWindowsResourceToolInfo(
            node = ctx.attr.node[DefaultInfo].files_to_run,
            modules = modules[0],
            script = ctx.file._editor,
        ),
        DefaultInfo(
            files = depset([modules[0], ctx.file._editor], transitive = [ctx.attr.node[DefaultInfo].files, runfiles.files]),
            runfiles = runfiles.merge(ctx.runfiles(files = [modules[0], ctx.file._editor])).merge(ctx.attr.node[DefaultInfo].default_runfiles),
        ),
    ]

electron_windows_resource_tool = rule(
    implementation = _impl,
    attrs = {
        "node": attr.label(mandatory = True, executable = True, cfg = "exec", doc = "Declared execution Node; the example uses hermeticbuild/nodejs sources."),
        "data": attr.label_list(cfg = "exec", doc = "Additional declared npm dependency closures, including linked-package runfiles."),
        "modules": attr.label(mandatory = True, cfg = "exec", doc = "Dependency root or linked resedit package directory; declare its closure in data."),
        "_editor": attr.label(default = Label("//electron/private:windows_resources.cjs"), allow_single_file = True),
    },
    doc = "Adapt pinned Node and resedit inputs for electron_app Windows metadata and integrity.",
)
