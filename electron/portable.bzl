"""Portable Windows executables compiled from declared NSIS tools."""

load(":defs.bzl", "ElectronAppInfo")
load(":nsis.bzl", "ElectronNsisToolInfo")

ElectronPortableInfo = provider(
    doc = "Portable launcher; it is not an NSIS updater installer.",
    fields = {"artifact": "Self-extracting portable executable."},
)

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "windows" or not app.artifact.is_directory:
        fail("electron_portable requires a Windows electron_app directory")
    architecture = None
    for name in ["x64", "arm64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            architecture = name
    if not architecture:
        fail("Unsupported portable payload architecture")
    tool = ctx.attr.tool[ElectronNsisToolInfo]
    if ctx.attr.compression == "7z" and not tool.archive_compiler:
        fail("7z compression requires an execution archive_compiler in the NSIS tool")
    output = ctx.actions.declare_file(ctx.label.name + ".exe")
    script = ctx.actions.declare_file(ctx.label.name + ".nsi")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    directories = getattr(app, "directory_manifest", None)
    ctx.actions.write(manifest, json.encode({
        "app": app.artifact.path,
        "package_json": app.package_json.path,
        "directory_manifest": directories.path if directories else "",
        "app_id": app.app_id,
        "product_name": app.product_name,
        "executable_name": app.executable_name,
        "app_filename": ctx.attr.app_filename,
        "build_version": getattr(app, "build_version", ""),
        "build_number": getattr(app, "build_number", ""),
        "architecture": architecture,
        "compression": ctx.attr.compression,
        "installer_icon": ctx.file.icon.path if ctx.file.icon else "",
        "compiler": tool.compiler.path,
        "data": tool.data.path,
        "archive_compiler": tool.archive_compiler.path if tool.archive_compiler else "",
        "verify_reproducible": ctx.attr.verify_reproducible,
    }))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path, script.path],
        inputs = [manifest, app.artifact, app.package_json, tool.data] + ([directories] if directories else []) + ([ctx.file.icon] if ctx.file.icon else []),
        tools = [tool.runner] + ([tool.archive_runner] if ctx.attr.compression == "7z" else []),
        outputs = [output, script],
        mnemonic = "ElectronPortable",
        progress_message = "Building portable Electron executable %{label}",
    )
    return [
        DefaultInfo(files = depset([output])),
        OutputGroupInfo(script = depset([script])),
        ElectronPortableInfo(artifact = output),
    ]

electron_portable = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "tool": attr.label(mandatory = True, providers = [ElectronNsisToolInfo], cfg = "exec"),
        "icon": attr.label(allow_single_file = [".ico"], doc = "Declared launcher icon."),
        "app_filename": attr.string(doc = "PORTABLE_EXECUTABLE_APP_FILENAME; defaults to the app executable stem."),
        "compression": attr.string(default = "7z", values = ["7z", "zlib", "bzip2", "lzma", "off"]),
        "verify_reproducible": attr.bool(default = False, doc = "Compile twice after relocating app/icon inputs; require identical executable and script bytes."),
        "_packager": attr.label(default = Label("//electron/private:portable_packager"), executable = True, cfg = "exec"),
        "_x64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
    doc = "Build a portable Windows launcher with unique temporary extraction, argument/environment forwarding, child exit status and owned cleanup. No installation or registration.",
)
