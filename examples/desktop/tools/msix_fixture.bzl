"""Minimal PE fixture for public MSIX rule and native Packaging API checks."""

load("@rules_electron//electron:defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [ctx.file.binary.path, output.path],
        inputs = [ctx.file.binary],
        outputs = [output],
        mnemonic = "ElectronMsixProbeApp",
    )
    return [
        DefaultInfo(files = depset([output])),
        ElectronAppInfo(
            artifact = output,
            platform = "windows",
            package_json = ctx.file.package_json,
            app_id = "org.example.MsixProbe",
            product_name = "MSIX Probe",
            executable_name = "helper",
            build_version = "1.0.0.7",
        ),
    ]

msix_fixture_app = rule(
    implementation = _impl,
    attrs = {
        "binary": attr.label(mandatory = True, allow_single_file = True),
        "package_json": attr.label(mandatory = True, allow_single_file = True),
        "_writer": attr.label(default = Label("@rules_electron//tests:msix_fixture_writer"), executable = True, cfg = "exec"),
    },
)
