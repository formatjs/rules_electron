"""electron-updater configuration and release feeds from final artifacts."""

load(":portable.bzl", "ElectronPortableInfo")

def _config_impl(ctx):
    if ctx.attr.provider == "generic":
        if not ctx.attr.url.startswith("https://") and not ctx.attr.url.startswith("http://"):
            fail("Generic feed url must use HTTP(S)")
        if ctx.attr.owner or ctx.attr.repo or ctx.attr.host or ctx.attr.private_repository:
            fail("GitHub options require provider=github")
        config = {"provider": "generic", "url": ctx.attr.url}
    else:
        if ctx.attr.url:
            fail("GitHub provider uses owner/repo instead of url")
        for name, value, characters in [
            ("owner", ctx.attr.owner, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"),
            ("repo", ctx.attr.repo, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_."),
        ]:
            if not value or value in [".", ".."] or any([c not in characters for c in value.elems()]):
                fail("Invalid GitHub " + name)
        config = {"provider": "github", "owner": ctx.attr.owner, "repo": ctx.attr.repo}
        if ctx.attr.host:
            if any([c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.[]:" for c in ctx.attr.host.elems()]):
                fail("GitHub host must be a hostname with optional port")
            config["host"] = ctx.attr.host
        if ctx.attr.private_repository:
            config["private"] = True
    if not ctx.attr.cache_name or ctx.attr.cache_name in [".", ".."] or any([c in ctx.attr.cache_name for c in ["/", "\\", ":"]]):
        fail("cache_name must be one nonempty directory name")
    if not ctx.attr.channel or any([c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in ctx.attr.channel.elems()]):
        fail("Invalid update channel")
    output = ctx.actions.declare_file(ctx.label.name + "/app-update.yml")
    config.update({
        "channel": ctx.attr.channel,
        "updaterCacheDirName": ctx.attr.cache_name,
    })
    if ctx.attr.publisher_names:
        config["publisherName"] = ctx.attr.publisher_names
    ctx.actions.write(output, json.encode_indent(config) + "\n")
    return [DefaultInfo(files = depset([output]))]

electron_update_config = rule(
    implementation = _config_impl,
    attrs = {
        "provider": attr.string(default = "generic", values = ["generic", "github"]),
        "url": attr.string(doc = "Required generic HTTP(S) feed base URL. Separate Windows/macOS CPU feeds by URL."),
        "owner": attr.string(doc = "GitHub repository owner; required for provider=github."),
        "repo": attr.string(doc = "GitHub repository name; required for provider=github."),
        "host": attr.string(doc = "Optional GitHub Enterprise hostname; HTTPS only."),
        "private_repository": attr.bool(doc = "GitHub private repository; runtime application supplies credentials, never rule attributes."),
        "channel": attr.string(default = "latest"),
        "cache_name": attr.string(mandatory = True, doc = "Stable updater cache directory name across releases."),
        "publisher_names": attr.string_list(doc = "Windows certificate publisher names used by electron-updater verification."),
    },
    doc = "Generate JSON-compatible YAML; map output to extra_resources app-update.yml before signing.",
)

def _feed_impl(ctx):
    artifacts = []
    inputs = [ctx.file.package_json]
    for target, filename in ctx.attr.artifacts.items():
        if ElectronPortableInfo in target:
            fail("Portable executables cannot be used as electron-updater installers")
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or files[0].is_directory:
            fail("Update artifacts must each provide one final file: %s" % target.label)
        inputs.append(files[0])
        artifacts.append({"source": files[0].path, "name": filename})
    output = ctx.actions.declare_directory(ctx.label.name)
    manifest = ctx.actions.declare_file(ctx.label.name + ".update.json")
    ctx.actions.write(manifest, json.encode({
        "artifacts": artifacts,
        "package_json": ctx.file.package_json.path,
        "platform": ctx.attr.platform,
        "architecture": ctx.attr.architecture,
        "channel": ctx.attr.channel,
        "release_date": ctx.attr.release_date,
        "release_notes": ctx.attr.release_notes,
        "staging_percentage": ctx.attr.staging_percentage,
        "blockmaps": ctx.attr.blockmaps,
        "embedded_blockmaps": ctx.attr.embedded_blockmaps,
        "admin_rights_required": ctx.attr.admin_rights_required,
    }))
    ctx.actions.run(
        executable = ctx.executable._feed,
        arguments = [manifest.path, output.path],
        inputs = inputs + [manifest],
        outputs = [output],
        mnemonic = "ElectronUpdateFeed",
        progress_message = "Generating Electron update feed %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_update_feed = rule(
    implementation = _feed_impl,
    attrs = {
        "artifacts": attr.label_keyed_string_dict(mandatory = True, allow_files = True, doc = "Final signed artifacts mapped to published filenames."),
        "package_json": attr.label(mandatory = True, allow_single_file = [".json"]),
        "platform": attr.string(mandatory = True, values = ["linux", "macos", "windows"]),
        "architecture": attr.string(mandatory = True, values = ["x64", "arm64"]),
        "channel": attr.string(default = "latest"),
        "release_date": attr.string(mandatory = True, doc = "Explicit RFC3339 UTC timestamp; never read the build clock."),
        "release_notes": attr.string(),
        "staging_percentage": attr.int(default = -1, doc = "0..100; -1 omits staged rollout metadata."),
        "embedded_blockmaps": attr.string_list(doc = "Linux AppImage filenames with embedded v2 maps; validate trailer and emit blockMapSize."),
        "blockmaps": attr.string_list(doc = "Published filenames needing external v2 blockmaps (NSIS/macOS ZIP). AppImage maps use embedded_blockmaps."),
        "admin_rights_required": attr.string_list(doc = "Windows installer filenames requiring the electron-updater elevation bridge."),
        "_feed": attr.label(default = Label("//electron/private:update_feed"), executable = True, cfg = "exec"),
    },
    doc = "Copy final artifacts, compute SHA-512/size, emit channel metadata and optional external blockmaps. Does not publish or install.",
)
