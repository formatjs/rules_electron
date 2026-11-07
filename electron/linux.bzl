"""Linux packages from assembled Electron apps."""

load("@rules_pkg//pkg:deb.bzl", "pkg_deb")
load(":defs.bzl", "ElectronAppInfo")

def _payload_impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "linux" or not app.artifact.is_directory:
        fail("electron_deb requires an assembled Linux app directory")
    architecture = None
    for name in ["amd64", "arm64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            architecture = name
    if not architecture:
        fail("Unsupported DEB target architecture")
    for target in ctx.attr.icons:
        if len(target.files.to_list()) != 1:
            fail("Each icon mapping requires exactly one file")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(manifest, json.encode({
        "app": app.artifact.path,
        "package_json": app.package_json.path,
        "app_id": app.app_id,
        "product_name": app.product_name,
        "executable_name": app.executable_name,
        "architecture": architecture,
        "revision": ctx.attr.revision,
        "description": ctx.attr.description,
        "categories": ctx.attr.categories,
        "protocols": ctx.attr.protocols,
        "file_associations": ctx.attr.file_associations,
        "icons": [{"source": f.path, "size": size} for t, size in ctx.attr.icons.items() for f in t.files.to_list()],
    }))
    ctx.actions.run(
        executable = ctx.executable._payload,
        arguments = [manifest.path, ctx.outputs.tar.path, ctx.outputs.version.path],
        inputs = [manifest, app.artifact, app.package_json] + [f for t in ctx.attr.icons for f in t.files.to_list()],
        outputs = [ctx.outputs.tar, ctx.outputs.version],
        mnemonic = "ElectronLinuxPayload",
        progress_message = "Packaging Electron Linux payload %{label}",
    )

_linux_payload = rule(
    implementation = _payload_impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "revision": attr.string(default = "1"),
        "description": attr.string(mandatory = True),
        "categories": attr.string_list(default = ["Utility"]),
        "protocols": attr.string_list(),
        "file_associations": attr.string_list_dict(doc = "MIME types mapped to filename globs, e.g. application/x-example: [*.example]."),
        "icons": attr.label_keyed_string_dict(allow_files = True, doc = "PNG labels mapped to pixel sizes, or SVG to scalable."),
        "_amd64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
        "_payload": attr.label(default = Label("//electron/private:linux_payload"), executable = True, cfg = "exec"),
    },
    outputs = {"tar": "%{name}.tar.gz", "version": "%{name}.version"},
)

def electron_deb(name, app, package_name, maintainer, description, depends, revision = "1", icons = {}, protocols = [], file_associations = {}, categories = ["Utility"], preinst = None, postinst = None, prerm = None, postrm = None, **kwargs):
    """Build a DEB with desktop integration; scripts are declared inputs, never run during packaging.

    Args:
        name: Target name.
        app: electron_app target.
        package_name: Debian package identifier.
        maintainer: Maintainer identity.
        description: Package description and desktop comment.
        depends: Explicit Debian runtime dependencies.
        revision: Debian package revision, separate from app version.
        icons: PNG sizes or scalable SVG mappings.
        protocols: URI schemes registered by the desktop entry.
        file_associations: MIME types and filename globs.
        categories: Desktop categories.
        preinst: Optional declared maintainer script.
        postinst: Optional declared maintainer script.
        prerm: Optional declared maintainer script.
        postrm: Optional declared maintainer script.
        **kwargs: Standard target attributes, including visibility.
    """
    compatible = ["@platforms//os:linux"] + kwargs.pop("target_compatible_with", [])
    _linux_payload(
        name = name + "_payload",
        app = app,
        revision = revision,
        description = description,
        icons = icons,
        protocols = protocols,
        file_associations = file_associations,
        categories = categories,
        target_compatible_with = compatible,
    )
    pkg_deb(
        name = name,
        out = name + ".deb",
        package_file_name = name + ".deb",
        data = ":" + name + "_payload.tar.gz",
        version_file = ":" + name + "_payload.version",
        architecture = select({
            Label("@platforms//cpu:x86_64"): "amd64",
            Label("@platforms//cpu:aarch64"): "arm64",
        }),
        package = package_name,
        maintainer = maintainer,
        description = description,
        depends = depends,
        preinst = preinst,
        postinst = postinst or Label("//electron/private:linux-maintainer.sh"),
        prerm = prerm,
        postrm = postrm or Label("//electron/private:linux-maintainer.sh"),
        section = "utils",
        priority = "optional",
        target_compatible_with = compatible,
        **kwargs
    )
