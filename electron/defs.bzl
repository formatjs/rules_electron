"""Native Electron app assembly. Runtime sources belong to the electron overlay."""

ElectronRuntimeInfo = provider(
    doc = "Target-platform runtime files, relative to the distribution root.",
    fields = {
        "entries": "List of structs with source, path and executable fields.",
        "archive": "Optional ZIP distribution artifact.",
        "exclude_files": "Exact archive-relative paths to omit.",
        "platform": "linux, macos or windows.",
        "languages": "Non-macOS ZIP locale stems to retain; empty keeps all.",
    },
)

def _platform(ctx):
    for name in ["linux", "macos", "windows"]:
        if ctx.target_platform_has_constraint(getattr(ctx.attr, "_" + name)[platform_common.ConstraintValueInfo]):
            return name
    fail("Unsupported Electron target OS")

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
    if bool(ctx.file.binary) == bool(ctx.file.archive):
        fail("Set exactly one of binary or archive")
    if ctx.file.binary and ctx.file.binary.is_directory:
        fail("Runtime binary must be a regular file")
    platform = _platform(ctx)
    binary_path = {"linux": "electron", "windows": "electron.exe", "macos": "Contents/MacOS/Electron"}[platform]
    entries = ([struct(source = ctx.file.binary, path = binary_path, executable = True)] if ctx.file.binary else []) + _entries(ctx.attr.files)
    if ctx.file.archive and entries:
        fail("Archive runtimes cannot also specify files")
    paths = {}
    for entry in entries:
        if entry.path in ["resources/app", "resources/app.asar", "resources/app.asar.unpacked"] or entry.path.startswith("resources/app/") or entry.path.startswith("resources/app.asar/") or entry.path.startswith("resources/app.asar.unpacked/"):
            fail("Runtime occupies app destination: %s" % entry.path)
        if entry.path in paths:
            fail("Duplicate runtime path: %s" % entry.path)
        paths[entry.path] = True
    return [
        ElectronRuntimeInfo(entries = entries, archive = ctx.file.archive, exclude_files = ctx.attr.exclude_files, platform = platform, languages = ctx.attr.languages),
        DefaultInfo(files = depset([entry.source for entry in entries] + ([ctx.file.archive] if ctx.file.archive else []))),
    ]

electron_runtime = rule(
    implementation = _runtime_impl,
    attrs = {
        "binary": attr.label(allow_single_file = True, doc = "Target Electron executable; mutually exclusive with archive."),
        "archive": attr.label(allow_single_file = [".zip"], doc = "Declared runtime ZIP, including macOS framework symlinks."),
        "exclude_files": attr.string_list(doc = "Exact ZIP-relative file paths to omit."),
        "languages": attr.string_list(doc = "Non-macOS ZIP locales to retain; empty retains all."),
        "files": attr.label_keyed_string_dict(allow_files = True, doc = "Runtime file labels mapped to distribution-relative paths."),
        "_linux": attr.label(default = Label("@platforms//os:linux")),
        "_macos": attr.label(default = Label("@platforms//os:osx")),
        "_windows": attr.label(default = Label("@platforms//os:windows")),
    },
    doc = "Adapt a runtime's declared files or ZIP for app assembly.",
)

def _app_impl(ctx):
    platform = _platform(ctx)
    runtime = ctx.attr.runtime[ElectronRuntimeInfo]
    if runtime.platform != platform:
        fail("Runtime and app target OS must match")
    if platform == "macos" and not ctx.executable.macos_signer:
        fail("macOS assembly requires an execution-platform macos_signer (rcodesign)")
    executable_name = _path(ctx.attr.executable_name)
    if "/" in executable_name:
        fail("executable_name must be a filename")
    app_entries = _entries(ctx.attr.srcs, allow_directories = True)
    resource_entries = _entries(ctx.attr.extra_resources, allow_directories = True)
    for entry in resource_entries:
        if entry.path.split("/")[0] in ["app", "app.asar", "app.asar.unpacked"]:
            fail("Extra resource occupies app destination: %s" % entry.path)
    resources = "Contents/Resources" if platform == "macos" else "resources"
    entries = [{"source": e.source.path, "path": e.path, "executable": e.executable} for e in runtime.entries]
    entries += [{"source": e.source.path, "path": resources + "/app/" + e.path, "executable": False, "directory": e.source.is_directory} for e in app_entries]
    entries += [{"source": e.source.path, "path": resources + "/" + e.path, "executable": e.executable, "directory": e.source.is_directory} for e in resource_entries]
    entries.append({"source": ctx.file.package_json.path, "path": resources + "/app/package.json", "executable": False})
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    output = ctx.actions.declare_file(ctx.label.name + ".zip") if platform == "macos" else ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.write(manifest, json.encode({
        "entries": entries,
        "asar": ctx.attr.asar,
        "asar_unpacked": ctx.attr.asar_unpacked,
        "fuses": ctx.attr.fuses,
        "executable_name": executable_name,
        "remove_package_scripts": ctx.attr.remove_package_scripts,
        "platform": platform,
        "runtime_archive": runtime.archive.path if runtime.archive else "",
        "exclude_files": runtime.exclude_files,
        "runtime_languages": runtime.languages,
        "product_name": ctx.attr.product_name or ctx.label.name,
        "app_id": ctx.attr.app_id,
    }))
    ctx.actions.run(
        executable = ctx.executable._assembler,
        arguments = [manifest.path, output.path] + ([ctx.executable.macos_signer.path] if platform == "macos" else []),
        inputs = depset([manifest, ctx.file.package_json] + ([runtime.archive] if runtime.archive else []) + [e.source for e in runtime.entries] + [e.source for e in app_entries] + [e.source for e in resource_entries]),
        tools = [ctx.executable.macos_signer] if platform == "macos" else [],
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
        "product_name": attr.string(),
        "app_id": attr.string(),
        "macos_signer": attr.label(executable = True, allow_single_file = True, cfg = "exec", doc = "Execution-platform rcodesign; required on macOS. Ad hoc signing only."),
        "remove_package_scripts": attr.bool(default = False),
        "fuses": attr.string_dict(doc = "Linux v1 fuse names mapped to on/off; see README."),
        "_assembler": attr.label(default = Label("//electron/private:assemble"), executable = True, cfg = "exec"),
        "_linux": attr.label(default = Label("@platforms//os:linux")),
        "_macos": attr.label(default = Label("@platforms//os:osx")),
        "_windows": attr.label(default = Label("@platforms//os:windows")),
    },
    doc = "Assemble a target-platform app using declared inputs and execution-platform tools.",
)
