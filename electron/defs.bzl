"""Native Electron app assembly. Runtime sources belong to the electron overlay."""

ElectronRuntimeInfo = provider(
    doc = "Target-platform runtime files, relative to the distribution root.",
    fields = {"entries": "List of structs with source, path and executable fields."},
)

def _path(path):
    if not path or path.startswith("/") or "\\" in path or ":" in path or "" in path.split("/") or "." in path.split("/") or ".." in path.split("/"):
        fail("Expected normalized relative path: %r" % path)
    return path

def _entries(files, allow_directories = False):
    entries = []
    for target, path in files.items():
        outputs = target[DefaultInfo].files.to_list()
        if len(outputs) != 1 or (outputs[0].is_directory and not allow_directories):
            fail("Each mapping needs one file%s: %s" % (" or tree artifact" if allow_directories else "", target.label))
        entries.append(struct(source = outputs[0], path = _path(path), executable = False))
    return entries

def _runtime_impl(ctx):
    if ctx.file.binary.is_directory:
        fail("Runtime binary must be a regular file")
    entries = [struct(source = ctx.file.binary, path = "electron", executable = True)] + _entries(ctx.attr.files)
    paths = {}
    for entry in entries:
        if entry.path in ["resources/app", "resources/app.asar", "resources/app.asar.unpacked"] or entry.path.startswith("resources/app/") or entry.path.startswith("resources/app.asar/") or entry.path.startswith("resources/app.asar.unpacked/"):
            fail("Runtime occupies app destination: %s" % entry.path)
        if entry.path in paths:
            fail("Duplicate runtime path: %s" % entry.path)
        paths[entry.path] = True
    return [
        ElectronRuntimeInfo(entries = entries),
        DefaultInfo(files = depset([entry.source for entry in entries])),
    ]

electron_runtime = rule(
    implementation = _runtime_impl,
    attrs = {
        "binary": attr.label(allow_single_file = True, mandatory = True, doc = "Target Electron executable; never executed during assembly."),
        "files": attr.label_keyed_string_dict(allow_files = True, doc = "Runtime file labels mapped to distribution-relative paths."),
    },
    doc = "Adapt a source runtime's declared outputs for Linux app assembly.",
)

def _app_impl(ctx):
    if not ctx.target_platform_has_constraint(ctx.attr._linux[platform_common.ConstraintValueInfo]):
        fail("electron_app currently supports Linux only")
    runtime = ctx.attr.runtime[ElectronRuntimeInfo]
    executable_name = _path(ctx.attr.executable_name)
    if "/" in executable_name:
        fail("executable_name must be a filename")
    app_entries = _entries(ctx.attr.srcs, allow_directories = True)
    resource_entries = _entries(ctx.attr.extra_resources, allow_directories = True)
    for entry in resource_entries:
        if entry.path.split("/")[0] in ["app", "app.asar", "app.asar.unpacked"]:
            fail("Extra resource occupies app destination: %s" % entry.path)
    entries = [{"source": e.source.path, "path": executable_name if e.path == "electron" else e.path, "executable": e.executable} for e in runtime.entries]
    entries += [{"source": e.source.path, "path": "resources/app/" + e.path, "executable": False, "directory": e.source.is_directory} for e in app_entries]
    entries += [{"source": e.source.path, "path": "resources/" + e.path, "executable": e.executable, "directory": e.source.is_directory} for e in resource_entries]
    entries.append({"source": ctx.file.package_json.path, "path": "resources/app/package.json", "executable": False})
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    output = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.write(manifest, json.encode({
        "entries": entries,
        "asar": ctx.attr.asar,
        "asar_unpacked": ctx.attr.asar_unpacked,
        "fuses": ctx.attr.fuses,
        "executable_name": executable_name,
        "remove_package_scripts": ctx.attr.remove_package_scripts,
    }))
    ctx.actions.run(
        executable = ctx.executable._assembler,
        arguments = [manifest.path, output.path],
        inputs = depset([manifest, ctx.file.package_json] + [e.source for e in runtime.entries] + [e.source for e in app_entries] + [e.source for e in resource_entries]),
        outputs = [output],
        mnemonic = "ElectronApp",
        progress_message = "Assembling Electron app %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

electron_app = rule(
    implementation = _app_impl,
    attrs = {
        "runtime": attr.label(mandatory = True, providers = [ElectronRuntimeInfo]),
        "package_json": attr.label(mandatory = True, allow_single_file = [".json"]),
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "Single files or tree artifacts mapped to app-relative paths."),
        "asar": attr.bool(default = False, doc = "Write resources/app.asar instead of resources/app."),
        "asar_unpacked": attr.string_list(doc = "Exact app-relative paths stored alongside ASAR; requires asar=True."),
        "extra_resources": attr.label_keyed_string_dict(allow_files = True, doc = "Files or tree artifacts mapped relative to resources/, outside ASAR."),
        "executable_name": attr.string(default = "electron"),
        "remove_package_scripts": attr.bool(default = False),
        "fuses": attr.string_dict(doc = "Linux v1 fuse names mapped to on/off; see README."),
        "_assembler": attr.label(default = Label("//electron/private:assemble"), executable = True, cfg = "exec"),
        "_linux": attr.label(default = Label("@platforms//os:linux")),
    },
    doc = "Assemble an unpacked Linux app using declared files and an execution-platform tool.",
)
