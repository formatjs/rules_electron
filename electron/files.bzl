"""Filtered views of declared files and generated directories."""

load(":matching.bzl", "ElectronFileMatcherInfo")

ElectronFileTreeInfo = provider(
    doc = "Tracked directories and logical symlinks relative to a target's single tree artifact.",
    fields = {
        "directory_manifest": "Optional JSON file containing normalized relative directory paths.",
        "symlink_manifest": "Optional JSON object mapping link paths to tree-root-relative targets; empty target means tree root.",
    },
)

def _impl(ctx):
    matcher = ctx.attr.file_matcher[ElectronFileMatcherInfo] if ctx.attr.file_matcher else None
    if ctx.attr.patterns and not matcher:
        fail("patterns requires file_matcher")
    entries, inputs = [], []
    has_symlinks = bool(ctx.attr.symlinks)
    for target, destination in ctx.attr.srcs.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Each file mapping needs one file or tree artifact: %s" % target.label)
        file = files[0]
        entry = {"source": file.path, "path": destination, "directory": file.is_directory}
        if ElectronFileTreeInfo in target:
            for field in ["directory_manifest", "symlink_manifest"]:
                metadata = getattr(target[ElectronFileTreeInfo], field, None)
                if metadata:
                    inputs.append(metadata)
                    entry[field] = metadata.path
                    if field == "symlink_manifest":
                        has_symlinks = True
        entries.append(entry)
        inputs.append(file)
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    output = ctx.actions.declare_directory(ctx.label.name)
    directories = ctx.actions.declare_file(ctx.label.name + ".directories.json")
    links = ctx.actions.declare_file(ctx.label.name + ".symlinks.json")
    ctx.actions.write(manifest, json.encode({
        "entries": entries,
        "directories": ctx.attr.directories,
        "symlinks": ctx.attr.symlinks,
        "patterns": ctx.attr.patterns,
        "file_matcher": {"node": matcher.node.executable.path, "script": matcher.script.path, "modules": matcher.modules.path} if matcher else None,
    }))
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [manifest.path, output.path, directories.path, links.path],
        inputs = depset(inputs + [manifest], transitive = [ctx.attr.file_matcher[DefaultInfo].files] if matcher else []),
        tools = [matcher.node] if matcher else [],
        outputs = [output, directories, links],
        mnemonic = "ElectronFiles",
    )
    return [DefaultInfo(files = depset([output])), ElectronFileTreeInfo(directory_manifest = directories, symlink_manifest = links if has_symlinks else None)]

electron_files = rule(
    implementation = _impl,
    attrs = {
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "File/tree labels mapped to output-relative paths. Empty destination mounts a tree at the output root."),
        "directories": attr.string_list(doc = "Explicit empty directory paths, filtered with the same destination patterns."),
        "symlinks": attr.string_dict(doc = "Logical link paths mapped to collection-root-relative targets. Carried in separate metadata, never tree-artifact symlinks."),
        "patterns": attr.string_list(doc = "Ordered minimatch inclusion/exclusion patterns over mapped paths, including empty directories; empty keeps all entries."),
        "file_matcher": attr.label(providers = [ElectronFileMatcherInfo], cfg = "exec"),
        "_writer": attr.label(default = Label("//electron/private:collect_files"), executable = True, cfg = "exec"),
    },
    doc = "Create a normalized, filtered tree for app inputs, extra files/resources or ASAR mappings.",
)
