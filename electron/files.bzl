"""Filtered views of declared files and generated directories."""

load(":matching.bzl", "ElectronFileMatcherInfo")

ElectronFileTreeInfo = provider(
    doc = "Tracked empty directory paths relative to a target's single tree artifact.",
    fields = {"directory_manifest": "JSON file containing normalized relative directory paths."},
)

def _impl(ctx):
    matcher = ctx.attr.file_matcher[ElectronFileMatcherInfo] if ctx.attr.file_matcher else None
    if ctx.attr.patterns and not matcher:
        fail("patterns requires file_matcher")
    entries, inputs = [], []
    for target, destination in ctx.attr.srcs.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Each file mapping needs one file or tree artifact: %s" % target.label)
        file = files[0]
        entry = {"source": file.path, "path": destination, "directory": file.is_directory}
        if ElectronFileTreeInfo in target:
            directories = target[ElectronFileTreeInfo].directory_manifest
            inputs.append(directories)
            entry["directory_manifest"] = directories.path
        entries.append(entry)
        inputs.append(file)
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    output = ctx.actions.declare_directory(ctx.label.name)
    directories = ctx.actions.declare_file(ctx.label.name + ".directories.json")
    ctx.actions.write(manifest, json.encode({
        "entries": entries,
        "patterns": ctx.attr.patterns,
        "file_matcher": {"node": matcher.node.executable.path, "script": matcher.script.path, "modules": matcher.modules.path} if matcher else None,
    }))
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [manifest.path, output.path, directories.path],
        inputs = inputs + [manifest] + ([matcher.modules, matcher.script] if matcher else []),
        tools = [matcher.node] if matcher else [],
        outputs = [output, directories],
        mnemonic = "ElectronFiles",
    )
    return [DefaultInfo(files = depset([output])), ElectronFileTreeInfo(directory_manifest = directories)]

electron_files = rule(
    implementation = _impl,
    attrs = {
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "File/tree labels mapped to output-relative paths. Empty destination mounts a tree at the output root."),
        "patterns": attr.string_list(doc = "Ordered minimatch inclusion/exclusion patterns over mapped paths, including empty directories; empty keeps all entries."),
        "file_matcher": attr.label(providers = [ElectronFileMatcherInfo], cfg = "exec"),
        "_writer": attr.label(default = Label("//electron/private:collect_files"), executable = True, cfg = "exec"),
    },
    doc = "Create a normalized, filtered tree for app inputs, extra files/resources or ASAR mappings.",
)
