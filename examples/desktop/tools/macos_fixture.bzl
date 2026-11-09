"""Deterministic public signing identities for native Squirrel.Mac smoke."""

load("@rules_electron//electron:defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "macos":
        fail("Public macOS fixture requires a macOS app")
    key = ctx.file._other_key if ctx.attr.wrong_identity else ctx.file._key
    certificate = ctx.actions.declare_file(ctx.label.name + ".pem")
    public = ctx.actions.declare_file(ctx.label.name + ".cer")
    output = ctx.actions.declare_file(ctx.label.name + ".zip")
    signer = ctx.attr._signer[DefaultInfo].files_to_run
    ctx.actions.run(
        executable = ctx.executable._certificate,
        arguments = [key.path, certificate.path, public.path],
        inputs = [key],
        outputs = [certificate, public],
        mnemonic = "ElectronPublicMacCertificate",
    )
    ctx.actions.run(
        executable = ctx.executable._sign,
        arguments = [app.artifact.path, key.path, certificate.path, ctx.executable._signer.path, ctx.file.entitlements.path, output.path],
        inputs = [app.artifact, key, certificate, ctx.file.entitlements],
        tools = [signer if signer.executable else ctx.executable._signer],
        outputs = [output],
        mnemonic = "ElectronPublicMacSign",
    )
    return [DefaultInfo(files = depset([output])), OutputGroupInfo(certificate = depset([public]))]

signed_macos_fixture = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "entitlements": attr.label(mandatory = True, allow_single_file = True),
        "wrong_identity": attr.bool(),
        "_key": attr.label(default = Label("@rules_electron//tests:public_fixture_key"), allow_single_file = True),
        "_other_key": attr.label(default = Label("@rules_electron//tests:other_public_fixture_key"), allow_single_file = True),
        "_certificate": attr.label(default = Label("@rules_electron//tests:public_test_certificate"), executable = True, cfg = "exec"),
        "_sign": attr.label(default = Label("@rules_electron//tests:macos_sign_fixture"), executable = True, cfg = "exec"),
        "_signer": attr.label(default = Label("@rcodesign_linux_x64//:rcodesign"), executable = True, cfg = "exec", allow_single_file = True),
    },
)
