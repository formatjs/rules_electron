"""Deterministic release archives from assembled apps."""

load(":defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    extension = {"zip": ".zip", "tar.gz": ".tar.gz"}[ctx.attr.format]
    output = ctx.actions.declare_file(ctx.label.name + extension)
    root = ctx.attr.root_name or (app.product_name + ".app" if app.platform == "macos" else app.executable_name)
    if app.platform == "macos" and not root.endswith(".app"):
        fail("macOS archive root_name must end in .app")
    if ctx.attr.compression_level < 0 or ctx.attr.compression_level > 9:
        fail("compression_level must be between 0 and 9")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(manifest, json.encode({
        "source": app.artifact.path,
        "platform": app.platform,
        "root_name": root,
        "format": ctx.attr.format,
        "compression_level": ctx.attr.compression_level,
    }))
    ctx.actions.run(
        executable = ctx.executable._archive,
        arguments = [manifest.path, output.path],
        inputs = [manifest, app.artifact],
        outputs = [output],
        mnemonic = "ElectronReleaseArchive",
        progress_message = "Archiving Electron app %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_archive = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "format": attr.string(default = "zip", values = ["zip", "tar.gz"]),
        "root_name": attr.string(doc = "Single top-level directory; defaults to executable_name or product_name.app."),
        "compression_level": attr.int(default = 6, doc = "0 through 9; ZIP level 0 stores entries."),
        "_archive": attr.label(default = Label("//electron/private:release_archive"), executable = True, cfg = "exec"),
    },
    doc = "Archive app bytes without executing target code; retain executable modes and relative symlinks.",
)
