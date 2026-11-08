"""Import immutable app outputs for native release packaging."""

load(":defs.bzl", "ElectronAppInfo")

def _impl(ctx):
    platform = None
    for name in ["linux", "macos", "windows"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            platform = name
    cpu = None
    for name in ["x86_64", "aarch64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            cpu = name
    if not platform or not cpu:
        fail("Prepackaged apps require Linux, macOS or Windows on x86_64 or aarch64")
    source = ctx.file.src
    if not source.is_directory and (platform != "macos" or not source.basename.endswith(".zip")):
        fail("src must be a tree artifact, or a macOS app ZIP")
    manifest = ctx.actions.declare_file(ctx.label.name + ".import.json")
    validation = ctx.actions.declare_file(ctx.label.name + ".validated")
    ctx.actions.write(manifest, json.encode({
        "source": source.path,
        "package_json": ctx.file.package_json.path,
        "platform": platform,
        "cpu": cpu,
        "executable_name": ctx.attr.executable_name,
        "product_name": ctx.attr.product_name,
        "app_id": ctx.attr.app_id,
        "build_version": ctx.attr.build_version,
        "build_number": ctx.attr.build_number,
    }))
    ctx.actions.run(
        executable = ctx.executable._validator,
        arguments = [manifest.path, validation.path],
        inputs = [source, ctx.file.package_json, manifest],
        outputs = [validation],
        mnemonic = "ElectronImportValidation",
        progress_message = "Validating prepackaged app %{label}",
    )
    return [
        ElectronAppInfo(
            artifact = source,
            platform = platform,
            package_json = ctx.file.package_json,
            executable_name = ctx.attr.executable_name,
            product_name = ctx.attr.product_name,
            app_id = ctx.attr.app_id,
            build_version = ctx.attr.build_version,
            build_number = ctx.attr.build_number,
        ),
        DefaultInfo(files = depset([source])),
        OutputGroupInfo(_validation = depset([validation])),
    ]

electron_prepackaged_app = rule(
    implementation = _impl,
    attrs = {
        "src": attr.label(mandatory = True, allow_single_file = True, doc = "App directory tree artifact or macOS .app ZIP; preserved byte-for-byte."),
        "package_json": attr.label(mandatory = True, allow_single_file = [".json"], doc = "Expected packaged name, version and main; shared with release rules."),
        "executable_name": attr.string(default = "electron", doc = "Executable basename, without Windows .exe suffix."),
        "product_name": attr.string(mandatory = True),
        "app_id": attr.string(mandatory = True),
        "build_version": attr.string(),
        "build_number": attr.string(),
        "_validator": attr.label(default = Label("//electron/private:prepackaged_validator"), executable = True, cfg = "exec"),
        "_linux": attr.label(default = Label("@platforms//os:linux")),
        "_macos": attr.label(default = Label("@platforms//os:osx")),
        "_windows": attr.label(default = Label("@platforms//os:windows")),
        "_x86_64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_aarch64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
    doc = "Import an app for archives/installers. Validate layout, CPU and identity without executing target code. Signature trust is a separate release check.",
)
