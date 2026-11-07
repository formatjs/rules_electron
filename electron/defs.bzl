"""Native Electron app assembly. Runtime sources belong to the electron overlay."""

ElectronRuntimeInfo = provider(
    doc = "Target-platform runtime files, relative to the distribution root.",
    fields = {"entries": "List of structs with source, path and executable fields."},
)

def _path(path):
    if not path or path.startswith("/") or "\\" in path or ":" in path or "" in path.split("/") or "." in path.split("/") or ".." in path.split("/"):
        fail("Expected normalized relative path: %r" % path)
    return path

def _entries(files):
    entries = []
    for target, path in files.items():
        outputs = target[DefaultInfo].files.to_list()
        if len(outputs) != 1 or outputs[0].is_directory:
            fail("Each mapping needs one regular file: %s" % target.label)
        entries.append(struct(source = outputs[0], path = _path(path), executable = False))
    return entries

def _runtime_impl(ctx):
    entries = [struct(source = ctx.file.binary, path = "electron", executable = True)] + _entries(ctx.attr.files)
    paths = {}
    for entry in entries:
        if entry.path == "resources/app.asar" or entry.path == "resources/app" or entry.path.startswith("resources/app/"):
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
    app_entries = _entries(ctx.attr.srcs)
    entries = [{"source": e.source.path, "path": e.path, "executable": e.executable} for e in runtime.entries]
    entries += [{"source": e.source.path, "path": "resources/app/" + e.path, "executable": False} for e in app_entries]
    entries.append({"source": ctx.file.package_json.path, "path": "resources/app/package.json", "executable": False})
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    output = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.write(manifest, json.encode(entries))
    ctx.actions.run(
        executable = ctx.executable._assembler,
        arguments = [manifest.path, output.path],
        inputs = depset([manifest, ctx.file.package_json] + [e.source for e in runtime.entries] + [e.source for e in app_entries]),
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
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "App file labels mapped to resources/app-relative paths."),
        "_assembler": attr.label(default = Label("//electron/private:assemble"), executable = True, cfg = "exec"),
        "_linux": attr.label(default = Label("@platforms//os:linux")),
    },
    doc = "Assemble an unpacked Linux app using declared files and an execution-platform tool.",
)
