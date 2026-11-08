"""Standalone ASAR archives with explicit unpacked files and header integrity."""

ElectronAsarInfo = provider(fields = {
    "archive": "ASAR artifact.",
    "unpacked": "Unpacked sidecar tree.",
    "header_hash": "File containing the raw JSON header SHA-256.",
})

def _impl(ctx):
    entries, inputs = [], []
    for target, destination in ctx.attr.srcs.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Each ASAR mapping needs one file or tree artifact: %s" % target.label)
        file = files[0]
        inputs.append(file)
        entries.append({"source": file.path, "path": destination, "directory": file.is_directory})
    archive = ctx.actions.declare_file(ctx.label.name + ".asar")
    unpacked = ctx.actions.declare_directory(ctx.label.name + ".asar.unpacked")
    digest = ctx.actions.declare_file(ctx.label.name + ".sha256")
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    ctx.actions.write(manifest, json.encode({"entries": entries, "unpacked": ctx.attr.unpacked}))
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [manifest.path, archive.path, unpacked.path, digest.path],
        inputs = inputs + [manifest],
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
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "File/tree labels mapped to archive-relative paths."),
        "unpacked": attr.string_list(doc = "Exact archive-relative files copied to the unpacked sidecar."),
        "_writer": attr.label(default = Label("//electron/private:asar_packager"), executable = True, cfg = "exec"),
    },
    doc = "Create an ASAR; use electron_app.extra_asars to stage its sidecar and embed integrity metadata.",
)
