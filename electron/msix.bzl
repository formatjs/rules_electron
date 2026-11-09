"""Unsigned MSIX packages from declared Windows apps and identity assets."""

load(":defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "windows":
        fail("electron_msix requires an assembled Windows app")
    architecture = None
    for name in ["x64", "arm64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            architecture = name
    if not architecture:
        fail("MSIX supports Windows x64/arm64")
    directories = getattr(app, "directory_manifest", None)
    output = ctx.actions.declare_file(ctx.label.name + ".msix")
    manifest = ctx.actions.declare_file(ctx.label.name + ".msix.json")
    logos = {name: getattr(ctx.file, name) for name in ["logo_44", "logo_150", "store_logo"]}
    ctx.actions.write(manifest, json.encode(dict({
        "app": app.artifact.path,
        "package_json": app.package_json.path,
        "identity_name": ctx.attr.identity_name or app.app_id,
        "publisher": ctx.attr.publisher,
        "publisher_display_name": ctx.attr.publisher_display_name,
        "product_name": app.product_name,
        "executable_name": app.executable_name,
        "architecture": architecture,
        "description": ctx.attr.description,
        "protocols": ctx.attr.protocols,
        "file_associations": ctx.attr.file_associations,
        "build_version": getattr(app, "build_version", ""),
        "build_number": getattr(app, "build_number", ""),
        "directory_manifest": directories.path if directories else "",
    }, **{name: file.path for name, file in logos.items()})))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path],
        inputs = [manifest, app.artifact, app.package_json] + logos.values() + ([directories] if directories else []),
        outputs = [output],
        mnemonic = "ElectronMsix",
        progress_message = "Packaging unsigned Electron MSIX %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_msix = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "identity_name": attr.string(doc = "MSIX identity; defaults to app_id. Must match eventual signing identity."),
        "publisher": attr.string(mandatory = True, doc = "Explicit certificate subject, such as CN=Example."),
        "publisher_display_name": attr.string(mandatory = True),
        "logo_44": attr.label(mandatory = True, allow_single_file = [".png"]),
        "logo_150": attr.label(mandatory = True, allow_single_file = [".png"]),
        "store_logo": attr.label(mandatory = True, allow_single_file = [".png"], doc = "50x50 PNG."),
        "description": attr.string(default = "Electron desktop application"),
        "protocols": attr.string_list(doc = "Lowercase URI schemes registered by Windows package deployment."),
        "file_associations": attr.string_dict(doc = "Lowercase file extension to display name. Advertise handlers without changing user defaults."),
        "_packager": attr.label(default = Label("//electron/private:msix_packager"), executable = True, cfg = "exec"),
        "_x64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
    doc = "Emit unsigned deterministic ZIP64 MSIX. Signing, deployment and OS registrations remain separate release stages. Empty directory leaves and symlinks currently fail explicitly.",
)
