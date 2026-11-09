"""Cross-built MSIX fixture; native hosts only execute its reader."""

def _impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".msix")
    architecture = "arm64" if ctx.target_platform_has_constraint(ctx.attr._arm64[platform_common.ConstraintValueInfo]) else "x64"
    inputs = [ctx.file.binary, ctx.file.package_json, ctx.file.logo_44, ctx.file.logo_150, ctx.file.store_logo]
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [file.path for file in inputs] + [architecture, output.path],
        inputs = inputs,
        outputs = [output],
        mnemonic = "ElectronMsixProbe",
    )
    return [DefaultInfo(files = depset([output]))]

msix_fixture = rule(
    implementation = _impl,
    attrs = {
        "binary": attr.label(mandatory = True, allow_single_file = True),
        "package_json": attr.label(mandatory = True, allow_single_file = True),
        "logo_44": attr.label(mandatory = True, allow_single_file = True),
        "logo_150": attr.label(mandatory = True, allow_single_file = True),
        "store_logo": attr.label(mandatory = True, allow_single_file = True),
        "_writer": attr.label(default = Label("@rules_electron//tests:msix_fixture_writer"), executable = True, cfg = "exec"),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
)
