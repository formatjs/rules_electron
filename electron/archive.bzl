"""Deterministic release archives from assembled apps."""

load(":defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    extension = "." + ctx.attr.format
    output = ctx.actions.declare_file(ctx.label.name + extension)
    root = ctx.attr.root_name or (app.product_name + ".app" if app.platform == "macos" else app.executable_name)
    if app.platform == "macos" and not root.endswith(".app"):
        fail("macOS archive root_name must end in .app")
    if ctx.attr.compression_level < 0 or ctx.attr.compression_level > 9:
        fail("compression_level must be between 0 and 9")
    if ctx.attr.format == "tar.bz2" and ctx.attr.compression_level == 0:
        fail("tar.bz2 compression_level must be between 1 and 9")
    if ctx.attr.format in ["7z", "tar.7z"] and not ctx.executable.sevenzip:
        fail("7z archives require a declared sevenzip execution tool")
    if ctx.attr.format == "tar.lz" and not ctx.executable.lzip:
        fail("tar.lz archives require a declared lzip execution tool")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    directories = getattr(app, "directory_manifest", None)
    ctx.actions.write(manifest, json.encode({
        "source": app.artifact.path,
        "platform": app.platform,
        "root_name": root,
        "format": ctx.attr.format,
        "compression_level": ctx.attr.compression_level,
        "directory_manifest": directories.path if directories else "",
        "sevenzip": ctx.executable.sevenzip.path if ctx.executable.sevenzip else "",
        "lzip": ctx.executable.lzip.path if ctx.executable.lzip else "",
    }))
    runner = ctx.attr.sevenzip[DefaultInfo].files_to_run if ctx.attr.sevenzip else None
    tools = [runner if runner and runner.executable else ctx.executable.sevenzip] if ctx.attr.sevenzip else []
    if ctx.attr.lzip:
        tools.append(ctx.attr.lzip[DefaultInfo].files_to_run)
    ctx.actions.run(
        executable = ctx.executable._archive,
        arguments = [manifest.path, output.path],
        inputs = [manifest, app.artifact] + ([directories] if directories else []),
        tools = tools,
        outputs = [output],
        mnemonic = "ElectronReleaseArchive",
        progress_message = "Archiving Electron app %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_archive = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "format": attr.string(default = "zip", values = ["zip", "tar", "tar.gz", "tar.xz", "tar.bz2", "7z", "tar.lz", "tar.7z"]),
        "root_name": attr.string(doc = "Single top-level directory; defaults to executable_name or product_name.app."),
        "compression_level": attr.int(default = 6, doc = "0 through 9; tar.bz2 requires 1 through 9. Ignored for plain tar. ZIP level 0 stores entries."),
        "sevenzip": attr.label(executable = True, cfg = "exec", allow_single_file = True, doc = "Required execution 7zip for 7z and tar.7z; no host tool discovery."),
        "lzip": attr.label(executable = True, cfg = "exec", allow_single_file = True, doc = "Required execution lzip for tar.lz. Source-built tool: @rules_electron//third_party:lzip."),
        "_archive": attr.label(default = Label("//electron/private:release_archive"), executable = True, cfg = "exec"),
    },
    doc = "Archive app bytes without executing target code; retain executable modes and relative symlinks.",
)
