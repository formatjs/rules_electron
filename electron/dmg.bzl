"""Deterministic HFS+ DMGs built on Linux with source-built execution tools."""

load(":defs.bzl", "ElectronAppInfo")

ElectronDmgInfo = provider(
    doc = "Final DMG and its shared unsigned filesystem image.",
    fields = {"image": "Final DMG artifact.", "unlicensed": "Unsigned image before license resources."},
)

_LICENSE_ATTRS = {
    "licenses": attr.label_keyed_string_dict(allow_files = [".txt", ".rtf"], doc = "Declared UTF-8 text/RTF files mapped to locales, such as en_US or ja_JP."),
    "license_texts": attr.label_keyed_string_dict(allow_files = [".txt"], doc = "Optional declared UTF-8 plain-text companions mapped to RTF license locales. Text must fit that locale's legacy encoding."),
    "license_default_language": attr.string(default = "en_US", doc = "Default license locale; must have a declared license."),
    "license_labels": attr.label(allow_single_file = [".json"], doc = "Optional per-locale languageName/agree/disagree/print/save/message labels."),
    "_license_tool": attr.label(default = Label("//electron/private:dmg_license_tool"), executable = True, cfg = "exec"),
}

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "macos":
        fail("electron_dmg requires a macOS app")
    manifest = ctx.actions.declare_file(ctx.label.name + ".dmg.json")
    output = ctx.actions.declare_file(ctx.label.name + ".dmg")
    base = ctx.actions.declare_file(ctx.label.name + ".unlicensed.dmg") if ctx.attr.licenses else output
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
        "background_image": ctx.file.background_image.path if ctx.file.background_image else "",
        "xorriso": ctx.executable._xorriso.path,
        "converter": ctx.executable._converter.path,
    }))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, base.path],
        inputs = [manifest, app.artifact] + [file for file in [ctx.file.volume_icon, ctx.file.background_image] if file],
        tools = [ctx.attr._xorriso[DefaultInfo].files_to_run, ctx.attr._converter[DefaultInfo].files_to_run],
        outputs = [base],
        mnemonic = "ElectronDmg",
        progress_message = "Packaging Electron DMG %{label}",
    )
    if ctx.attr.license_labels and not ctx.attr.licenses:
        fail("license_labels requires licenses")
    if ctx.attr.license_texts and not ctx.attr.licenses:
        fail("license_texts requires licenses")
    if ctx.attr.licenses:
        _license_action(ctx, base, output)
    return [
        DefaultInfo(files = depset([output])),
        ElectronDmgInfo(image = output, unlicensed = base),
        OutputGroupInfo(unlicensed = depset([base])),
    ]

def _license_action(ctx, base, output):
    entries = []
    texts = []
    inputs = [base]
    for target, locale in ctx.attr.licenses.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or files[0].is_directory:
            fail("Each DMG license must provide one text or RTF file")
        entries.append({"source": files[0].path, "locale": locale})
        inputs.append(files[0])
    for target, locale in ctx.attr.license_texts.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or files[0].is_directory:
            fail("Each DMG license text must provide one UTF-8 text file")
        texts.append({"source": files[0].path, "locale": locale})
        inputs.append(files[0])
    legal = ctx.actions.declare_file(ctx.label.name + ".licenses.json")
    ctx.actions.write(legal, json.encode({
        "source": base.path,
        "licenses": entries,
        "license_texts": texts,
        "default_language": ctx.attr.license_default_language,
        "labels": ctx.file.license_labels.path if ctx.file.license_labels else "",
    }))
    ctx.actions.run(
        executable = ctx.executable._license_tool,
        arguments = [legal.path, output.path],
        inputs = inputs + [legal] + ([ctx.file.license_labels] if ctx.file.license_labels else []),
        outputs = [output],
        mnemonic = "ElectronDmgLicense",
        progress_message = "Adding Electron DMG licenses %{label}",
    )

def _license_impl(ctx):
    if not ctx.attr.licenses:
        fail("electron_dmg_license requires declared licenses")
    image = ctx.attr.image
    base = image[ElectronDmgInfo].unlicensed if ElectronDmgInfo in image else ctx.file.image
    output = ctx.actions.declare_file(ctx.label.name + ".dmg")
    _license_action(ctx, base, output)
    return [DefaultInfo(files = depset([output])), ElectronDmgInfo(image = output, unlicensed = base)]

electron_dmg_license = rule(
    implementation = _license_impl,
    attrs = dict(_LICENSE_ATTRS, image = attr.label(mandatory = True, allow_single_file = [".dmg"])),
    doc = "Apply declared licenses to a shared DMG base or raw unsigned, unlicensed image. Filesystem bytes stay unchanged.",
)

electron_dmg = rule(
    implementation = _impl,
    attrs = dict(_LICENSE_ATTRS, **{
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
        "background_image": attr.label(allow_single_file = [".png"], doc = "Declared Finder background PNG; requires finder_window and overrides background_color."),
        "_xorriso": attr.label(default = Label("//electron/tools:xorriso"), executable = True, cfg = "exec"),
        "_converter": attr.label(default = Label("//electron/tools:dmg"), executable = True, cfg = "exec"),
        "_packager": attr.label(default = Label("//electron/private:dmg_packager"), executable = True, cfg = "exec"),
    }),
    doc = "Package immutable macOS app bytes as a read-only zlib-compressed HFS+ UDIF image, without target execution or host tools.",
)
