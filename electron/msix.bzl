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
    association_icons = []
    for target, extension in ctx.attr.file_association_icons.items():
        files = target.files.to_list()
        if len(files) != 1 or not files[0].basename.endswith(".png"):
            fail("Each MSIX document icon requires one PNG file")
        association_icons.append({"source": files[0].path, "extension": extension})
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
        "file_association_icons": association_icons,
        "build_version": getattr(app, "build_version", ""),
        "build_number": getattr(app, "build_number", ""),
        "directory_manifest": directories.path if directories else "",
    }, **{name: file.path for name, file in logos.items()})))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path],
        inputs = [manifest, app.artifact, app.package_json] + logos.values() + ([directories] if directories else []) + [file for target in ctx.attr.file_association_icons for file in target.files.to_list()],
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
        "file_association_icons": attr.label_keyed_string_dict(allow_files = [".png"], doc = "Declared PNG icons mapped to registered file extensions. Packaged as uap:Logo assets."),
        "_packager": attr.label(default = Label("//electron/private:msix_packager"), executable = True, cfg = "exec"),
        "_x64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
    doc = "Emit unsigned deterministic ZIP64 MSIX. Signing, deployment and OS registrations remain separate release stages. Empty directory leaves and symlinks currently fail explicitly.",
)

def _appinstaller_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".appinstaller")
    manifest = ctx.actions.declare_file(ctx.label.name + ".appinstaller.json")
    options = {name: getattr(ctx.attr, name) for name in [
        "appinstaller_uri",
        "package_uri",
        "appinstaller_version",
        "check_on_launch",
        "hours_between_update_checks",
        "show_prompt",
        "update_blocks_activation",
        "automatic_background_task",
        "force_update_from_any_version",
        "update_uris",
        "repair_uris",
        "allow_http_loopback",
    ]}
    options["package"] = ctx.file.package.path
    ctx.actions.write(manifest, json.encode(options))
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [manifest.path, output.path],
        inputs = [manifest, ctx.file.package],
        outputs = [output],
        mnemonic = "ElectronAppInstaller",
        progress_message = "Writing MSIX update metadata %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_msix_appinstaller = rule(
    implementation = _appinstaller_impl,
    attrs = {
        "package": attr.label(mandatory = True, allow_single_file = [".msix", ".msixbundle"]),
        "appinstaller_uri": attr.string(mandatory = True, doc = "Public URL of this update descriptor."),
        "package_uri": attr.string(mandatory = True, doc = "Public URL of the final MSIX package or bundle."),
        "appinstaller_version": attr.string(doc = "Four-component descriptor version; defaults to MSIX identity version."),
        "check_on_launch": attr.bool(default = True),
        "hours_between_update_checks": attr.int(default = 24),
        "show_prompt": attr.bool(),
        "update_blocks_activation": attr.bool(),
        "automatic_background_task": attr.bool(),
        "force_update_from_any_version": attr.bool(doc = "Explicitly permit version downgrades."),
        "update_uris": attr.string_list(),
        "repair_uris": attr.string_list(),
        "allow_http_loopback": attr.bool(doc = "Permit explicit HTTP loopback fixtures; production URLs require HTTPS."),
        "_writer": attr.label(default = Label("//electron/private:appinstaller_writer"), executable = True, cfg = "exec"),
    },
    doc = "Write deterministic 2021 App Installer XML from final MSIX package or bundle identity. No publication, signing or deployment.",
)

def _bundle_impl(ctx):
    packages = ctx.files.packages
    if not packages or any([file.is_directory or file.extension.lower() != "msix" for file in packages]):
        fail("electron_msix_bundle requires selected MSIX package files")
    output = ctx.actions.declare_file(ctx.label.name + ".msixbundle")
    manifest = ctx.actions.declare_file(ctx.label.name + ".bundle.json")
    ctx.actions.write(manifest, json.encode({
        "packages": [file.path for file in packages],
        "package_names": ctx.attr.package_names,
        "bundle_version": ctx.attr.bundle_version,
    }))
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [manifest.path, output.path],
        inputs = [manifest] + packages,
        outputs = [output],
        mnemonic = "ElectronMsixBundle",
        progress_message = "Bundling native MSIX packages %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_msix_bundle = rule(
    implementation = _bundle_impl,
    attrs = {
        "packages": attr.label_list(mandatory = True, allow_files = [".msix"], doc = "Package files or groups. One application package per CPU; matching identity/manifests required."),
        "package_names": attr.string_dict(doc = "Optional CPU-to-filename mapping; defaults to package-<cpu>.msix."),
        "bundle_version": attr.string(doc = "Explicit four-component version; defaults to the shared package version."),
        "_writer": attr.label(default = Label("//electron/private:msix_bundle_writer"), executable = True, cfg = "exec"),
    },
    doc = "Emit an embedded deterministic MSIX bundle. Packages stay unchanged; signing is a separate release stage.",
)
