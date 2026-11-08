"""Declared package identity shared by app assembly and release feeds."""

def _package_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [ctx.file.src.path, output.path, ctx.attr.version, "1" if ctx.attr.remove_scripts else "0", ctx.file.extra_metadata.path if ctx.file.extra_metadata else "", json.encode(ctx.attr.remove_fields)],
        inputs = [ctx.file.src] + ([ctx.file.extra_metadata] if ctx.file.extra_metadata else []),
        outputs = [output],
        mnemonic = "ElectronPackageJson",
    )
    return [DefaultInfo(files = depset([output]))]

electron_package_json = rule(
    implementation = _package_impl,
    attrs = {
        "src": attr.label(mandatory = True, allow_single_file = [".json"]),
        "version": attr.string(doc = "Explicit SemVer override; empty validates and retains the source version."),
        "remove_scripts": attr.bool(default = False),
        "extra_metadata": attr.label(allow_single_file = [".json"], doc = "Declared JSON object deep-merged into the source manifest. Arrays and scalar values replace existing values."),
        "remove_fields": attr.string_list(doc = "Top-level fields removed after merging. Version remains required; explicit version wins."),
        "_writer": attr.label(default = Label("//electron/private:package_json"), executable = True, cfg = "exec"),
    },
    doc = "Validate package SemVer and write deterministic JSON. Share this output between electron_app and electron_update_feed.",
)
