"""Deterministic HFS+ DMGs built on Linux with source-built execution tools."""

load(":defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "macos":
        fail("electron_dmg requires a macOS app")
    manifest = ctx.actions.declare_file(ctx.label.name + ".dmg.json")
    output = ctx.actions.declare_file(ctx.label.name + ".dmg")
    ctx.actions.write(manifest, json.encode({
        "source": app.artifact.path,
        "app_name": app.product_name + ".app",
        "volume_name": ctx.attr.volume_name or app.product_name,
        "source_date_epoch": ctx.attr.source_date_epoch,
        "applications_link": ctx.attr.applications_link,
        "xorriso": ctx.executable._xorriso.path,
        "converter": ctx.executable._converter.path,
    }))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path],
        inputs = [manifest, app.artifact],
        tools = [ctx.attr._xorriso[DefaultInfo].files_to_run, ctx.attr._converter[DefaultInfo].files_to_run],
        outputs = [output],
        mnemonic = "ElectronDmg",
        progress_message = "Packaging Electron DMG %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_dmg = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "volume_name": attr.string(doc = "Volume label, up to 32 UTF-8 bytes; defaults to product_name."),
        "source_date_epoch": attr.int(default = 0, doc = "Explicit Unix timestamp for all image dates; defaults to epoch."),
        "applications_link": attr.bool(default = True, doc = "Add the standard /Applications link beside the app."),
        "_xorriso": attr.label(default = Label("//electron/tools:xorriso"), executable = True, cfg = "exec"),
        "_converter": attr.label(default = Label("//electron/tools:dmg"), executable = True, cfg = "exec"),
        "_packager": attr.label(default = Label("//electron/private:dmg_packager"), executable = True, cfg = "exec"),
    },
    doc = "Package immutable macOS app bytes as a read-only zlib-compressed HFS+ UDIF image, without target execution or host tools.",
)
