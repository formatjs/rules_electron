"""Standalone ASAR archives with explicit unpacked files and header integrity."""

load(":files.bzl", "ElectronFileTreeInfo")
load(":matching.bzl", "ElectronFileMatcherInfo")

ElectronAsarInfo = provider(fields = {
    "archive": "ASAR artifact.",
    "unpacked": "Unpacked sidecar tree.",
    "header_hash": "File containing the raw JSON header SHA-256.",
})

def _impl(ctx):
    matcher = ctx.attr.file_matcher[ElectronFileMatcherInfo] if ctx.attr.file_matcher else None
    if ctx.attr.unpacked_patterns and not matcher:
        fail("unpacked_patterns requires file_matcher")
    entries, inputs = [], []
    for target, destination in ctx.attr.srcs.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Each ASAR mapping needs one file or tree artifact: %s" % target.label)
        file = files[0]
        inputs.append(file)
        entry = {"source": file.path, "path": destination, "directory": file.is_directory}
        if ElectronFileTreeInfo in target:
            directories = target[ElectronFileTreeInfo].directory_manifest
            inputs.append(directories)
            entry["directory_manifest"] = directories.path
        entries.append(entry)
    archive = ctx.actions.declare_file(ctx.label.name + ".asar")
    unpacked = ctx.actions.declare_directory(ctx.label.name + ".asar.unpacked")
    digest = ctx.actions.declare_file(ctx.label.name + ".sha256")
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    ctx.actions.write(manifest, json.encode({
        "entries": entries,
        "unpacked": ctx.attr.unpacked,
        "unpacked_patterns": ctx.attr.unpacked_patterns,
        "symlinks": ctx.attr.symlinks,
        "file_matcher": {"node": matcher.node.executable.path, "script": matcher.script.path, "modules": matcher.modules.path} if matcher else None,
    }))
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [manifest.path, archive.path, unpacked.path, digest.path],
        inputs = inputs + [manifest] + ([matcher.modules, matcher.script] if matcher else []),
        tools = [matcher.node] if matcher else [],
        outputs = [archive, unpacked, digest],
        mnemonic = "ElectronAsar",
    )
    return [
        DefaultInfo(files = depset([archive])),
        ElectronAsarInfo(archive = archive, unpacked = unpacked, header_hash = digest),
        OutputGroupInfo(unpacked = depset([unpacked]), header_hash = depset([digest])),
    ]

electron_asar = rule(
    implementation = _impl,
    attrs = {
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "File/tree labels mapped to archive-relative paths; empty destination mounts a tree at the archive root."),
        "unpacked": attr.string_list(doc = "Exact archive-relative files copied to the unpacked sidecar."),
        "unpacked_patterns": attr.string_list(doc = "Ordered minimatch inclusion/exclusion patterns; selected files join explicit unpacked paths. Requires file_matcher."),
        "file_matcher": attr.label(providers = [ElectronFileMatcherInfo], cfg = "exec"),
        "symlinks": attr.string_dict(doc = "Link paths mapped to archive-root-relative targets; empty target denotes archive root. Encoded in ASAR, without filesystem symlinks."),
        "_writer": attr.label(default = Label("//electron/private:asar_packager"), executable = True, cfg = "exec"),
    },
    doc = "Create an ASAR; use electron_app.extra_asars to stage its sidecar and embed integrity metadata.",
)
