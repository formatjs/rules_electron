"""Linux packages from assembled Electron apps."""

load("@rules_pkg//pkg:deb.bzl", "pkg_deb")
load(":defs.bzl", "ElectronAppInfo")

def _payload_impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    if app.platform != "linux":
        fail("electron_deb requires an assembled Linux app")
    architecture = None
    for name in ["amd64", "arm64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            architecture = name
    if not architecture:
        fail("Unsupported DEB target architecture")
    for target in ctx.attr.icons.keys() + ctx.attr.file_association_icons.keys():
        if len(target.files.to_list()) != 1:
            fail("Each icon mapping requires exactly one file")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    directories = getattr(app, "directory_manifest", None)
    ctx.actions.write(manifest, json.encode({
        "app": app.artifact.path,
        "directory_manifest": directories.path if directories else "",
        "setuid_sandbox": ctx.attr.setuid_sandbox,
        "package_type": ctx.attr.package_type,
        "package_json": app.package_json.path,
        "app_id": app.app_id,
        "product_name": app.product_name,
        "executable_name": app.executable_name,
        "architecture": architecture,
        "revision": ctx.attr.revision or getattr(app, "build_number", "") or "1",
        "description": ctx.attr.description,
        "categories": ctx.attr.categories,
        "protocols": ctx.attr.protocols,
        "file_associations": ctx.attr.file_associations,
        "icons": [{"source": f.path, "size": size} for t, size in ctx.attr.icons.items() for f in t.files.to_list()],
        "file_association_icons": [{"source": f.path, "mime_type": mime} for t, mime in ctx.attr.file_association_icons.items() for f in t.files.to_list()],
    }))
    ctx.actions.run(
        executable = ctx.executable._payload,
        arguments = [manifest.path, ctx.outputs.tar.path, ctx.outputs.version.path],
        inputs = [manifest, app.artifact, app.package_json] + ([directories] if directories else []) + [f for t in ctx.attr.icons.keys() + ctx.attr.file_association_icons.keys() for f in t.files.to_list()],
        outputs = [ctx.outputs.tar, ctx.outputs.version],
        mnemonic = "ElectronLinuxPayload",
        progress_message = "Packaging Electron Linux payload %{label}",
    )

_linux_payload = rule(
    implementation = _payload_impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "revision": attr.string(),
        "setuid_sandbox": attr.bool(default = False),
        "package_type": attr.string(default = "deb", values = ["deb", "rpm"]),
        "description": attr.string(mandatory = True),
        "categories": attr.string_list(default = ["Utility"]),
        "protocols": attr.string_list(),
        "file_associations": attr.string_list_dict(doc = "MIME types mapped to filename globs, e.g. application/x-example: [*.example]."),
        "icons": attr.label_keyed_string_dict(allow_files = True, doc = "PNG labels mapped to pixel sizes, or SVG to scalable."),
        "file_association_icons": attr.label_keyed_string_dict(allow_files = True, doc = "Declared PNG/SVG icons mapped to registered MIME types. PNG dimensions choose the hicolor size; SVG is scalable."),
        "_amd64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_arm64": attr.label(default = Label("@platforms//cpu:aarch64")),
        "_payload": attr.label(default = Label("//electron/private:linux_payload"), executable = True, cfg = "exec"),
    },
    outputs = {"tar": "%{name}.tar.gz", "version": "%{name}.version"},
)

def electron_deb(name, app, package_name, maintainer, description, depends, revision = "", icons = {}, protocols = [], file_associations = {}, categories = ["Utility"], preinst = None, postinst = None, prerm = None, postrm = None, setuid_sandbox = False, file_association_icons = {}, **kwargs):
    """Build a DEB with desktop integration; scripts are declared inputs, never run during packaging.

    Args:
        name: Target name.
        app: electron_app target.
        package_name: Debian package identifier.
        maintainer: Maintainer identity.
        description: Package description and desktop comment.
        depends: Explicit Debian runtime dependencies.
        revision: Debian revision; defaults to app build_number, then 1.
        icons: PNG sizes or scalable SVG mappings.
        protocols: URI schemes registered by the desktop entry.
        file_associations: MIME types and filename globs.
        categories: Desktop categories.
        preinst: Optional declared maintainer script.
        postinst: Optional declared maintainer script.
        prerm: Optional declared maintainer script.
        postrm: Optional declared maintainer script.
        setuid_sandbox: Install a matching chrome-sandbox ELF helper as root:root 4755.
        file_association_icons: PNG/SVG labels mapped to registered MIME types.
        **kwargs: Standard target attributes, including visibility.
    """
    compatible = ["@platforms//os:linux"] + kwargs.pop("target_compatible_with", [])
    _linux_payload(
        name = name + "_payload",
        app = app,
        revision = revision,
        description = description,
        icons = icons,
        file_association_icons = file_association_icons,
        protocols = protocols,
        file_associations = file_associations,
        categories = categories,
        setuid_sandbox = setuid_sandbox,
        target_compatible_with = compatible,
    )
    pkg_deb(
        name = name,
        out = "_" + name + ".deb",
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

def _rpm_impl(ctx):
    app = ctx.attr.app[ElectronAppInfo]
    architecture = None
    for name in ["x86_64", "aarch64"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            architecture = name
    if not architecture or app.platform != "linux":
        fail("electron_rpm requires a Linux x86_64/aarch64 app")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    output = ctx.actions.declare_file(ctx.label.name + ".rpm")
    scripts = {name: getattr(ctx.file, name) for name in ["prein", "postin", "preun", "postun"]}
    ctx.actions.write(manifest, json.encode(dict({
        "payload": ctx.file.payload.path,
        "package_json": app.package_json.path,
        "package_name": ctx.attr.package_name,
        "architecture": architecture,
        "release": ctx.attr.release or getattr(app, "build_number", "") or "1",
        "summary": ctx.attr.summary,
        "description": ctx.attr.description,
        "license": ctx.attr.license,
        "requires": ctx.attr.requires,
        "maintainer": ctx.attr.maintainer,
    }, **{name: file.path if file else "" for name, file in scripts.items()})))
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [manifest.path, output.path],
        inputs = [manifest, ctx.file.payload, app.package_json] + [file for file in scripts.values() if file],
        outputs = [output],
        mnemonic = "ElectronRpm",
        progress_message = "Building RPM %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

_rpm = rule(
    implementation = _rpm_impl,
    attrs = {
        "app": attr.label(mandatory = True, providers = [ElectronAppInfo]),
        "payload": attr.label(mandatory = True, allow_single_file = [".tar.gz"]),
        "package_name": attr.string(mandatory = True),
        "summary": attr.string(mandatory = True),
        "description": attr.string(mandatory = True),
        "license": attr.string(mandatory = True),
        "requires": attr.string_list(),
        "maintainer": attr.string(),
        "release": attr.string(),
        "prein": attr.label(allow_single_file = True),
        "postin": attr.label(allow_single_file = True),
        "preun": attr.label(allow_single_file = True),
        "postun": attr.label(allow_single_file = True),
        "_packager": attr.label(default = Label("//electron/private:rpm_packager"), executable = True, cfg = "exec"),
        "_x86_64": attr.label(default = Label("@platforms//cpu:x86_64")),
        "_aarch64": attr.label(default = Label("@platforms//cpu:aarch64")),
    },
)

def electron_rpm(name, app, package_name, summary, description, license, requires = [], maintainer = "", release = "", icons = {}, protocols = [], file_associations = {}, file_association_icons = {}, categories = ["Utility"], setuid_sandbox = False, prein = None, postin = None, preun = None, postun = None, **kwargs):
    """Build an unsigned RPM v4; dependencies and install-time scripts are explicit.

    Args:
        name: Target name.
        app: Assembled Linux app.
        package_name: RPM package name.
        summary: Short package summary.
        description: Package and desktop description.
        license: SPDX license expression for the packaged app.
        requires: RPM capabilities, optionally followed by a comparison and version.
        maintainer: Package maintainer identity.
        release: RPM release; defaults to app build_number, then 1.
        icons: PNG size/SVG scalable application icons.
        protocols: URI schemes.
        file_associations: MIME types mapped to filename globs.
        file_association_icons: PNG/SVG labels mapped to registered MIME types.
        categories: Desktop categories.
        setuid_sandbox: Install matching chrome-sandbox as root:root 4755.
        prein: Declared pre-install shell script.
        postin: Declared post-install script; default refreshes desktop/MIME/icon caches.
        preun: Declared pre-uninstall shell script.
        postun: Declared post-uninstall script; default refreshes desktop/MIME/icon caches.
        **kwargs: Standard target attributes.
    """
    compatible = ["@platforms//os:linux"] + kwargs.pop("target_compatible_with", [])
    _linux_payload(
        name = name + "_payload",
        app = app,
        revision = release,
        package_type = "rpm",
        description = description,
        icons = icons,
        file_association_icons = file_association_icons,
        protocols = protocols,
        file_associations = file_associations,
        categories = categories,
        setuid_sandbox = setuid_sandbox,
        target_compatible_with = compatible,
    )
    _rpm(
        name = name,
        app = app,
        payload = ":" + name + "_payload.tar.gz",
        package_name = package_name,
        summary = summary,
        description = description,
        license = license,
        requires = requires,
        maintainer = maintainer,
        release = release,
        prein = prein,
        postin = postin or Label("//electron/private:rpm-maintainer.sh"),
        preun = preun,
        postun = postun or Label("//electron/private:rpm-maintainer.sh"),
        target_compatible_with = compatible,
        **kwargs
    )
