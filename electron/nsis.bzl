"""Per-user Windows installers from declared apps and execution tools."""

load(":defs.bzl", "ElectronAppInfo")

ElectronNsisToolInfo = provider(
    doc = "Execution makensis and its declared NSISDIR tree.",
    fields = {"compiler": "Compiler executable.", "runner": "Compiler runfiles.", "data": "NSISDIR tree.", "archive_compiler": "Optional execution 7zip.", "archive_runner": "Optional 7zip runfiles."},
)

def _tool_impl(ctx):
    files = ctx.attr.data[DefaultInfo].files.to_list()
    if len(files) != 1 or not files[0].is_directory:
        fail("data must provide one NSISDIR tree")
    runner = ctx.attr.compiler[DefaultInfo].files_to_run
    archive_runner = ctx.attr.archive_compiler[DefaultInfo].files_to_run if ctx.attr.archive_compiler else None
    return [
        ElectronNsisToolInfo(
            compiler = ctx.executable.compiler,
            runner = runner if runner.executable else ctx.executable.compiler,
            data = files[0],
            archive_compiler = ctx.executable.archive_compiler,
            archive_runner = archive_runner if archive_runner and archive_runner.executable else ctx.executable.archive_compiler,
        ),
        DefaultInfo(files = depset([files[0]], transitive = [ctx.attr.compiler[DefaultInfo].files] + ([ctx.attr.archive_compiler[DefaultInfo].files] if ctx.attr.archive_compiler else []))),
    ]

electron_nsis_tool = rule(
    implementation = _tool_impl,
    attrs = {
        "compiler": attr.label(mandatory = True, executable = True, allow_single_file = True, cfg = "exec"),
        "data": attr.label(mandatory = True, cfg = "exec", doc = "Tree containing Include, Stubs, Plugins and Contrib, including the Unicode WinShell plugin for shortcut identity."),
        "archive_compiler": attr.label(executable = True, allow_single_file = True, cfg = "exec", doc = "Declared 7zip; required for 7z payload compression."),
    },
)

def _installer_impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "windows" or not app.artifact.is_directory:
        fail("electron_nsis requires a Windows electron_app directory")
    architecture = None
    for name in ["x64", "arm64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            architecture = name
    if not architecture:
        fail("Unsupported NSIS payload architecture")
    tool = ctx.attr.tool[ElectronNsisToolInfo]
    if ctx.attr.compression == "7z" and not tool.archive_compiler:
        fail("7z compression requires an execution archive_compiler in the NSIS tool")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    output = ctx.actions.declare_file(ctx.label.name + ".exe")
    script = ctx.actions.declare_file(ctx.label.name + ".nsi")
    ctx.actions.write(manifest, json.encode({
        "app": app.artifact.path,
        "package_json": app.package_json.path,
        "build_version": getattr(app, "build_version", ""),
        "build_number": getattr(app, "build_number", ""),
        "app_id": app.app_id,
        "product_name": app.product_name,
        "executable_name": app.executable_name,
        "compiler": tool.compiler.path,
        "data": tool.data.path,
        "protocols": ctx.attr.protocols,
        "file_associations": ctx.attr.file_associations,
        "app_user_model_id": ctx.attr.app_user_model_id,
        "desktop_shortcut": ctx.attr.desktop_shortcut,
        "verify_reproducible": ctx.attr.verify_reproducible,
        "compression": ctx.attr.compression,
        "updater_cache_name": ctx.attr.updater_cache_name,
        "architecture": architecture,
        "archive_compiler": tool.archive_compiler.path if tool.archive_compiler else "",
    }))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path, script.path],
        inputs = [manifest, app.artifact, app.package_json, tool.data],
        tools = [tool.runner] + ([tool.archive_runner] if ctx.attr.compression == "7z" else []),
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
        "file_associations": attr.string_dict(doc = "Lowercase extensions (including dot) mapped to descriptions. Registers per-user Open With and Default Apps handlers; preserves user defaults."),
        "desktop_shortcut": attr.bool(default = False),
        "app_user_model_id": attr.string(doc = "Shortcut AppUserModelID; defaults to the app ID. Match app.setAppUserModelId at runtime."),
        "compression": attr.string(default = "7z", values = ["7z", "zlib", "bzip2", "lzma", "off"]),
        "updater_cache_name": attr.string(doc = "Stable app-update.yml cache name; seed current installer for differential updates."),
        "verify_reproducible": attr.bool(default = False, doc = "Compile twice in different directories and require identical installer bytes."),
        "_packager": attr.label(default = Label("//electron/private:nsis_packager"), executable = True, cfg = "exec"),
        "_x64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
    doc = "Build an unsigned per-user NSIS installer/uninstaller. Release signing follows packaging.",
)
