"""Per-user Windows installers from declared apps and execution tools."""

load(":defs.bzl", "ElectronAppInfo")

ElectronNsisToolInfo = provider(
    doc = "Execution makensis and its declared NSISDIR tree.",
    fields = {"compiler": "Compiler executable.", "runner": "Compiler runfiles.", "data": "NSISDIR tree."},
)

def _tool_impl(ctx):
    files = ctx.attr.data[DefaultInfo].files.to_list()
    if len(files) != 1 or not files[0].is_directory:
        fail("data must provide one NSISDIR tree")
    runner = ctx.attr.compiler[DefaultInfo].files_to_run
    return [
        ElectronNsisToolInfo(compiler = ctx.executable.compiler, runner = runner if runner.executable else ctx.executable.compiler, data = files[0]),
        DefaultInfo(files = depset([files[0]], transitive = [ctx.attr.compiler[DefaultInfo].files])),
    ]

electron_nsis_tool = rule(
    implementation = _tool_impl,
    attrs = {
        "compiler": attr.label(mandatory = True, executable = True, allow_single_file = True, cfg = "exec"),
        "data": attr.label(mandatory = True, cfg = "exec", doc = "Tree containing Include, Stubs, Plugins and Contrib."),
    },
)

def _installer_impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "windows" or not app.artifact.is_directory:
        fail("electron_nsis requires a Windows electron_app directory")
    tool = ctx.attr.tool[ElectronNsisToolInfo]
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    output = ctx.actions.declare_file(ctx.label.name + ".exe")
    script = ctx.actions.declare_file(ctx.label.name + ".nsi")
    ctx.actions.write(manifest, json.encode({
        "app": app.artifact.path,
        "package_json": app.package_json.path,
        "app_id": app.app_id,
        "product_name": app.product_name,
        "executable_name": app.executable_name,
        "compiler": tool.compiler.path,
        "data": tool.data.path,
        "protocols": ctx.attr.protocols,
        "desktop_shortcut": ctx.attr.desktop_shortcut,
        "verify_reproducible": ctx.attr.verify_reproducible,
        "compression": ctx.attr.compression,
        "updater_cache_name": ctx.attr.updater_cache_name,
    }))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path, script.path],
        inputs = [manifest, app.artifact, app.package_json, tool.data],
        tools = [tool.runner],
        outputs = [output, script],
        mnemonic = "ElectronNsis",
        progress_message = "Building Windows installer %{label}",
    )
    return [DefaultInfo(files = depset([output])), OutputGroupInfo(script = depset([script]))]

electron_nsis = rule(
    implementation = _installer_impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "tool": attr.label(mandatory = True, providers = [ElectronNsisToolInfo], cfg = "exec"),
        "protocols": attr.string_list(doc = "Per-user URI schemes; existing foreign registrations cause installation to fail."),
        "desktop_shortcut": attr.bool(default = False),
        "compression": attr.string(default = "zlib", values = ["zlib", "bzip2", "lzma", "off"]),
        "updater_cache_name": attr.string(doc = "Stable app-update.yml cache name; seed current installer for differential updates."),
        "verify_reproducible": attr.bool(default = False, doc = "Compile twice in different directories and require identical installer bytes."),
        "_packager": attr.label(default = Label("//electron/private:nsis_packager"), executable = True, cfg = "exec"),
    },
    doc = "Build an unsigned per-user NSIS installer/uninstaller. Release signing follows packaging.",
)
