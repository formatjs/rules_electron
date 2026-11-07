"""Declared execution tools for Windows resource editing."""

ElectronWindowsResourceToolInfo = provider(
    doc = "Execution Node and pinned module closure for PE resources.",
    fields = {
        "node": "Execution-platform Node FilesToRunProvider.",
        "modules": "Tree containing node_modules/resedit and its pinned closure.",
        "script": "Resource editor script.",
    },
)

def _impl(ctx):
    modules = ctx.attr.modules[DefaultInfo].files.to_list()
    if len(modules) != 1 or not modules[0].is_directory:
        fail("modules must provide one tree containing node_modules")
    return [
        ElectronWindowsResourceToolInfo(
            node = ctx.attr.node[DefaultInfo].files_to_run,
            modules = modules[0],
            script = ctx.file._editor,
        ),
        DefaultInfo(files = depset([modules[0], ctx.file._editor], transitive = [ctx.attr.node[DefaultInfo].files])),
    ]

electron_windows_resource_tool = rule(
    implementation = _impl,
    attrs = {
        "node": attr.label(mandatory = True, executable = True, cfg = "exec", doc = "Declared execution Node; the example uses hermeticbuild/nodejs sources."),
        "modules": attr.label(mandatory = True, cfg = "exec", doc = "Tree retaining node_modules/resedit and pe-library paths."),
        "_editor": attr.label(default = Label("//electron/private:windows_resources.cjs"), allow_single_file = True),
    },
    doc = "Adapt pinned Node and resedit inputs for electron_app Windows metadata and integrity.",
)
