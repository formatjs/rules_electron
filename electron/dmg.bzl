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
        "volume_icon": ctx.file.volume_icon.path if ctx.file.volume_icon else "",
        "finder_window": ctx.attr.finder_window,
        "app_position": ctx.attr.app_position,
        "applications_position": ctx.attr.applications_position,
        "icon_size": ctx.attr.icon_size,
        "text_size": ctx.attr.text_size,
        "background_color": ctx.attr.background_color,
        "xorriso": ctx.executable._xorriso.path,
        "converter": ctx.executable._converter.path,
    }))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path],
        inputs = [manifest, app.artifact] + ([ctx.file.volume_icon] if ctx.file.volume_icon else []),
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
        "volume_icon": attr.label(allow_single_file = [".icns"], doc = "Declared volume ICNS, separate from the signed app bundle."),
        "source_date_epoch": attr.int(default = 0, doc = "Explicit Unix timestamp for all image dates; defaults to epoch."),
        "applications_link": attr.bool(default = True, doc = "Add the standard /Applications link beside the app."),
        "finder_window": attr.int_list(doc = "Optional Cocoa x, y, width, height (bottom-left screen origin). Enables icon view and auto-open metadata."),
        "app_position": attr.int_list(default = [160, 180], doc = "App icon center within Finder window."),
        "applications_position": attr.int_list(default = [480, 180], doc = "Applications link icon center within Finder window."),
        "icon_size": attr.int(default = 128, doc = "Finder icon size, 16..512, when finder_window is set."),
        "text_size": attr.int(default = 14, doc = "Finder label size, 10..16, when finder_window is set."),
        "background_color": attr.string(default = "#ffffff", doc = "Finder background #RRGGBB when finder_window is set."),
        "_xorriso": attr.label(default = Label("//electron/tools:xorriso"), executable = True, cfg = "exec"),
        "_converter": attr.label(default = Label("//electron/tools:dmg"), executable = True, cfg = "exec"),
        "_packager": attr.label(default = Label("//electron/private:dmg_packager"), executable = True, cfg = "exec"),
    },
    doc = "Package immutable macOS app bytes as a read-only zlib-compressed HFS+ UDIF image, without target execution or host tools.",
)
