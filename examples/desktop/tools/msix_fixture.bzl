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

def _signed_impl(ctx):
    extension = ctx.file.src.extension
    certificate = ctx.actions.declare_file(ctx.label.name + ".pem")
    public_certificate = ctx.actions.declare_file(ctx.label.name + ".cer")
    signed = ctx.actions.declare_file(ctx.label.name + "." + extension)
    tampered = ctx.actions.declare_file(ctx.label.name + ".tampered." + extension) if ctx.attr.tamper_file else None
    config = ctx.actions.declare_file(ctx.label.name + ".openssl.cnf")
    ctx.actions.write(config, "")
    ctx.actions.run(
        executable = ctx.executable._certificate,
        arguments = [ctx.file._key.path, certificate.path, public_certificate.path],
        inputs = [ctx.file._key],
        outputs = [certificate, public_certificate],
        mnemonic = "ElectronPublicTestCertificate",
    )
    ctx.actions.run(
        executable = ctx.executable._sign,
        arguments = [ctx.executable._signer.path, ctx.file.src.path, ctx.file._key.path, certificate.path, config.path, signed.path, tampered.path if tampered else "", ctx.attr.tamper_file],
        inputs = [ctx.file.src, ctx.file._key, certificate, config],
        tools = [ctx.attr._signer[DefaultInfo].files_to_run],
        outputs = [signed] + ([tampered] if tampered else []),
        mnemonic = "ElectronPublicTestSign",
    )
    return [
        DefaultInfo(files = depset([signed, public_certificate] + ([tampered] if tampered else []))),
        OutputGroupInfo(signed = depset([signed])),
    ]

signed_msix_fixture = rule(
    implementation = _signed_impl,
    attrs = {
        "src": attr.label(mandatory = True, allow_single_file = [".msix", ".msixbundle"]),
        "tamper_file": attr.string(default = "helper.exe"),
        "_key": attr.label(default = Label("@rules_electron//tests:public_fixture_key"), allow_single_file = True),
        "_certificate": attr.label(default = Label("@rules_electron//tests:public_test_certificate"), executable = True, cfg = "exec"),
        "_sign": attr.label(default = Label("@rules_electron//tests:msix_sign_fixture"), executable = True, cfg = "exec"),
        "_signer": attr.label(default = Label("@rules_electron//electron/tools:osslsigncode"), executable = True, cfg = "exec"),
    },
)
