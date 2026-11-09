"""Source-built type-2 AppImages from assembled Linux apps."""

load(":defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "linux":
        fail("electron_appimage requires an assembled Linux app")
    if not app.app_id:
        fail("electron_appimage requires app_id on its electron_app")
    architecture = None
    for name in ["x64", "arm64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            architecture = name
    if not architecture:
        fail("AppImage supports Linux x64/arm64")
    directories = getattr(app, "directory_manifest", None)
    output = ctx.actions.declare_file(ctx.label.name + ".AppImage")
    manifest = ctx.actions.declare_file(ctx.label.name + ".appimage.json")
    ctx.actions.write(manifest, json.encode({
        "app": app.artifact.path,
        "package_json": app.package_json.path,
        "runtime": ctx.file.runtime.path,
        "launcher": ctx.file._launcher.path,
        "mksquashfs": ctx.executable._mksquashfs.path,
        "app_id": app.app_id,
        "product_name": app.product_name,
        "executable_name": app.executable_name,
        "architecture": architecture,
        "icon": ctx.file.icon.path,
        "description": ctx.attr.description,
        "categories": ctx.attr.categories,
        "protocols": ctx.attr.protocols,
        "file_associations": ctx.attr.file_associations,
        "directory_manifest": directories.path if directories else "",
        "compressor": ctx.attr.compressor,
        "compression_level": ctx.attr.compression_level,
        "embedded_blockmap": ctx.attr.embedded_blockmap,
    }))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path],
        inputs = [manifest, app.artifact, app.package_json, ctx.file.runtime, ctx.file._launcher, ctx.file.icon] + ([directories] if directories else []),
        tools = [ctx.attr._mksquashfs[DefaultInfo].files_to_run],
        outputs = [output],
        mnemonic = "ElectronAppImage",
        progress_message = "Packaging Electron AppImage %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_appimage = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "icon": attr.label(mandatory = True, allow_single_file = [".png", ".svg"]),
        "description": attr.string(),
        "categories": attr.string_list(default = ["Utility"]),
        "protocols": attr.string_list(),
        "file_associations": attr.string_list(doc = "Declared MIME types in the desktop entry."),
        "compressor": attr.string(default = "zstd", values = ["gzip", "zstd"]),
        "compression_level": attr.int(default = 9),
        "embedded_blockmap": attr.bool(default = True),
        "runtime": attr.label(default = Label("//electron/tools:appimage_runtime"), allow_single_file = True, doc = "Declared static PIE runtime for target CPU; never executed during packaging."),
        "_launcher": attr.label(default = Label("//electron/tools:appimage_apprun"), allow_single_file = True),
        "_mksquashfs": attr.label(default = Label("//electron/tools:mksquashfs"), executable = True, cfg = "exec"),
        "_packager": attr.label(default = Label("//electron/private:appimage_packager"), executable = True, cfg = "exec"),
        "_x64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
    doc = "Assemble declared AppDir metadata and source-built runtime; emit deterministic AppImage with optional updater v2 embedded map.",
)
