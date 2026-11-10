"""electron-updater configuration and release feeds from final artifacts."""

load(":portable.bzl", "ElectronPortableInfo")

def _storage_config(attr):
    if attr.url or attr.owner or attr.repo or attr.host or attr.private_repository:
        fail("Object storage cannot use generic/GitHub options")
    if not attr.region or any([c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in attr.region.elems()]):
        fail("Object storage requires an explicit region")
    if attr.path and any([not part or part in [".", ".."] or any([c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~" for c in part.elems()]) for part in attr.path.split("/")]):
        fail("Object storage path must contain normalized URL-safe segments")
    name = attr.bucket if attr.provider == "s3" else attr.space_name
    if len(name) < 3 or len(name) > 63 or any([
        not part or part.startswith("-") or part.endswith("-") or any([c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in part.elems()])
        for part in name.split(".")
    ]):
        fail("Object storage requires a DNS-compatible bucket/space name")
    config = {"provider": attr.provider, "region": attr.region}
    if attr.path:
        config["path"] = attr.path
    if attr.provider == "spaces":
        if attr.bucket or attr.endpoint or attr.accelerate or "." in name:
            fail("Spaces requires space_name; S3-only options are invalid")
        config["name"] = name
    else:
        if attr.space_name:
            fail("space_name requires provider=spaces")
        if attr.accelerate and (attr.endpoint or "." in name):
            fail("S3 acceleration cannot use an endpoint or dotted bucket")
        config["bucket"] = name
        if attr.accelerate:
            config["accelerate"] = True
        if attr.endpoint:
            authority = attr.endpoint[len("https://"):].split("/")[0]
            if (not attr.endpoint.startswith("https://") or not authority or
                any([c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.[]:" for c in authority.elems()]) or
                any([c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/%[]!$&'()*+,;=" for c in attr.endpoint.elems()])):
                fail("S3 endpoint must be an HTTPS URL without credentials, query or fragment")
            config["endpoint"] = attr.endpoint.rstrip("/")
    return config

def _config_impl(ctx):
    if ctx.attr.provider in ["s3", "spaces"]:
        config = _storage_config(ctx.attr)
    elif ctx.attr.bucket or ctx.attr.space_name or ctx.attr.region or ctx.attr.path or ctx.attr.endpoint or ctx.attr.accelerate:
        fail("Object storage options require provider=s3 or provider=spaces")
    elif ctx.attr.provider == "generic":
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
        "provider": attr.string(default = "generic", values = ["generic", "github", "s3", "spaces"]),
        "url": attr.string(doc = "Required generic HTTP(S) feed base URL. Separate Windows/macOS CPU feeds by URL."),
        "owner": attr.string(doc = "GitHub repository owner; required for provider=github."),
        "repo": attr.string(doc = "GitHub repository name; required for provider=github."),
        "host": attr.string(doc = "Optional GitHub Enterprise hostname; HTTPS only."),
        "private_repository": attr.bool(doc = "GitHub private repository; runtime application supplies credentials, never rule attributes."),
        "bucket": attr.string(doc = "Public S3 bucket; requires provider=s3."),
        "space_name": attr.string(doc = "Public DigitalOcean Space; requires provider=spaces."),
        "region": attr.string(doc = "Explicit object-storage region; never discovered from host credentials."),
        "path": attr.string(doc = "Object-storage prefix, using normalized URL-safe segments."),
        "endpoint": attr.string(doc = "Optional public S3-compatible HTTPS API endpoint, excluding the bucket."),
        "accelerate": attr.bool(doc = "Use the S3 transfer-acceleration download endpoint."),
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
