"""Native Electron app assembly. Runtime sources belong to the electron overlay."""

load(":asar.bzl", "ElectronAsarInfo")
load(":matching.bzl", "ElectronFileMatcherInfo")
load(":windows.bzl", "ElectronWindowsResourceToolInfo")

ElectronAppInfo = provider(
    doc = "Assembled target app and identity for downstream packaging rules.",
    fields = {
        "artifact": "App directory or macOS bundle ZIP.",
        "platform": "linux, macos or windows.",
        "package_json": "App package manifest.",
        "executable_name": "Main executable basename.",
        "product_name": "Display name.",
        "app_id": "Application identifier.",
        "build_version": "Explicit native build version override.",
        "build_number": "Explicit build iteration.",
    },
)

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

def _entries(files, allow_directories = False, allow_root = False):
    entries = []
    for target, path in files.items():
        outputs = target[DefaultInfo].files.to_list()
        if len(outputs) != 1 or (outputs[0].is_directory and not allow_directories):
            fail("Each mapping needs one file%s: %s" % (" or tree artifact" if allow_directories else "", target.label))
        destination = "" if allow_root and outputs[0].is_directory and path == "" else _path(path)
        entries.append(struct(source = outputs[0], path = destination, executable = False))
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
    if platform != "macos" and (ctx.attr.macos_protocols or ctx.attr.macos_protocol_roles):
        fail("macOS protocols require a macOS target")
    if platform != "macos" and ctx.file.macos_icon:
        fail("macos_icon requires a macOS target")
    if platform != "macos" and (ctx.file.macos_entitlements or ctx.file.macos_entitlements_inherit or ctx.attr.macos_hardened_runtime):
        fail("macOS signing settings require a macOS target")
    if platform == "macos" and not ctx.executable.macos_signer:
        fail("macOS assembly requires an execution-platform macos_signer (rcodesign)")
    signer = ctx.attr.macos_signer[DefaultInfo].files_to_run if platform == "macos" else None
    windows_tool = ctx.attr.windows_resource_tool[ElectronWindowsResourceToolInfo] if ctx.attr.windows_resource_tool else None
    matcher = ctx.attr.file_matcher[ElectronFileMatcherInfo] if ctx.attr.file_matcher else None
    if ctx.attr.asar_unpacked_patterns and (not ctx.attr.asar or not matcher):
        fail("asar_unpacked_patterns requires asar=True and file_matcher")
    if platform == "windows" and (ctx.attr.windows_metadata or ctx.file.windows_icon or ctx.attr.build_version or ctx.attr.build_number or ctx.attr.fuses.get("enableEmbeddedAsarIntegrityValidation") == "on") and not windows_tool:
        fail("Windows metadata, icons, build identity and embedded integrity require windows_resource_tool")
    if platform != "windows" and (windows_tool or ctx.attr.windows_metadata or ctx.file.windows_icon):
        fail("Windows resource options require a Windows target")
    for key in ctx.attr.windows_metadata:
        if key not in ["CompanyName", "FileDescription", "InternalName", "LegalCopyright", "OriginalFilename", "ProductName"]:
            fail("Unsupported Windows metadata key: %s" % key)
    executable_name = _path(ctx.attr.executable_name)
    if "/" in executable_name:
        fail("executable_name must be a filename")
    app_entries = _entries(ctx.attr.srcs, allow_directories = True, allow_root = True)
    resource_entries = _entries(ctx.attr.extra_resources, allow_directories = True)
    extra_entries = _entries(ctx.attr.extra_files, allow_directories = True)
    extra_asars, asar_inputs = [], []
    for target, destination in ctx.attr.extra_asars.items():
        archive = target[ElectronAsarInfo]
        extra_asars.append({"archive": archive.archive.path, "unpacked": archive.unpacked.path, "header_hash": archive.header_hash.path, "path": _path(destination)})
        asar_inputs += [archive.archive, archive.unpacked, archive.header_hash]
    for entry in resource_entries:
        if entry.path.split("/")[0] in ["app", "app.asar", "app.asar.unpacked"]:
            fail("Extra resource occupies app destination: %s" % entry.path)
    resources = "Contents/Resources" if platform == "macos" else "resources"
    entries = [{"source": e.source.path, "path": e.path, "executable": e.executable} for e in runtime.entries]
    entries += [{"source": e.source.path, "path": resources + "/app" + ("/" + e.path if e.path else ""), "executable": False, "directory": e.source.is_directory} for e in app_entries]
    entries += [{"source": e.source.path, "path": resources + "/" + e.path, "executable": e.executable, "directory": e.source.is_directory} for e in resource_entries]
    entries.append({"source": ctx.file.package_json.path, "path": resources + "/app/package.json", "executable": False})
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json")
    output = ctx.actions.declare_file(ctx.label.name + ".zip") if platform == "macos" else ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.write(manifest, json.encode({
        "entries": entries,
        "extra_files": [{"source": e.source.path, "path": e.path, "directory": e.source.is_directory} for e in extra_entries],
        "extra_asars": extra_asars,
        "asar": ctx.attr.asar,
        "asar_unpacked": ctx.attr.asar_unpacked,
        "asar_unpacked_patterns": ctx.attr.asar_unpacked_patterns,
        "file_matcher": {"node": matcher.node.executable.path, "script": matcher.script.path, "modules": matcher.modules.path} if matcher else None,
        "asar_symlinks": ctx.attr.asar_symlinks,
        "fuses": ctx.attr.fuses,
        "executable_name": executable_name,
        "remove_package_scripts": ctx.attr.remove_package_scripts,
        "platform": platform,
        "runtime_archive": runtime.archive.path if runtime.archive else "",
        "exclude_files": runtime.exclude_files,
        "runtime_languages": runtime.languages,
        "product_name": ctx.attr.product_name or ctx.label.name,
        "app_id": ctx.attr.app_id,
        "macos_protocols": ctx.attr.macos_protocols,
        "macos_protocol_roles": ctx.attr.macos_protocol_roles,
        "macos_icon": ctx.file.macos_icon.path if ctx.file.macos_icon else "",
        "macos_entitlements": ctx.file.macos_entitlements.path if ctx.file.macos_entitlements else "",
        "macos_entitlements_inherit": ctx.file.macos_entitlements_inherit.path if ctx.file.macos_entitlements_inherit else "",
        "macos_hardened_runtime": ctx.attr.macos_hardened_runtime,
        "windows_metadata": ctx.attr.windows_metadata,
        "windows_icon": ctx.file.windows_icon.path if ctx.file.windows_icon else "",
        "build_version": ctx.attr.build_version,
        "build_number": ctx.attr.build_number,
        "windows_resource_tool": {
            "node": windows_tool.node.executable.path,
            "modules": windows_tool.modules.path,
            "script": windows_tool.script.path,
        } if windows_tool else None,
    }))
    ctx.actions.run(
        executable = ctx.executable._assembler,
        arguments = [manifest.path, output.path] + ([ctx.executable.macos_signer.path] if platform == "macos" else []),
        inputs = depset([manifest, ctx.file.package_json] + ([runtime.archive] if runtime.archive else []) + [e.source for e in runtime.entries] + [e.source for e in app_entries] + [e.source for e in resource_entries] + [e.source for e in extra_entries] + asar_inputs + ([ctx.file.macos_icon] if ctx.file.macos_icon else []) + ([ctx.file.macos_entitlements] if ctx.file.macos_entitlements else []) + ([ctx.file.macos_entitlements_inherit] if ctx.file.macos_entitlements_inherit else []) + ([ctx.file.windows_icon] if ctx.file.windows_icon else []) + ([windows_tool.modules, windows_tool.script] if windows_tool else []) + ([matcher.modules, matcher.script] if matcher else [])),
        tools = ([signer if signer.executable else ctx.executable.macos_signer] if signer else []) + ([windows_tool.node] if windows_tool else []) + ([matcher.node] if matcher else []),
        outputs = [output],
        mnemonic = "ElectronApp",
        progress_message = "Assembling Electron app %{label}",
    )
    return [
        ElectronAppInfo(
            artifact = output,
            platform = platform,
            package_json = ctx.file.package_json,
            executable_name = executable_name,
            product_name = ctx.attr.product_name or ctx.label.name,
            app_id = ctx.attr.app_id,
            build_version = ctx.attr.build_version,
            build_number = ctx.attr.build_number,
        ),
        DefaultInfo(files = depset([output])),
    ]

electron_app = rule(
    implementation = _app_impl,
    attrs = {
        "runtime": attr.label(mandatory = True, providers = [ElectronRuntimeInfo]),
        "package_json": attr.label(mandatory = True, allow_single_file = [".json"]),
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "Single files or tree artifacts mapped to app-relative paths; empty destination mounts a tree at the app root."),
        "asar": attr.bool(default = False, doc = "Write resources/app.asar instead of resources/app."),
        "asar_unpacked": attr.string_list(doc = "Exact app-relative paths stored alongside ASAR; requires asar=True."),
        "asar_unpacked_patterns": attr.string_list(doc = "Ordered minimatch inclusion/exclusion patterns; selected files join explicit unpacked paths. Requires asar=True and file_matcher."),
        "file_matcher": attr.label(providers = [ElectronFileMatcherInfo], cfg = "exec"),
        "asar_symlinks": attr.string_dict(doc = "ASAR link paths mapped to archive-root-relative targets; empty target denotes archive root. Requires asar=True."),
        "extra_resources": attr.label_keyed_string_dict(allow_files = True, doc = "Files or tree artifacts mapped relative to resources/, outside ASAR."),
        "extra_files": attr.label_keyed_string_dict(allow_files = True, doc = "Files or tree artifacts mapped to Contents/ on macOS, distribution root elsewhere; outside ASAR."),
        "extra_asars": attr.label_keyed_string_dict(providers = [ElectronAsarInfo], doc = "Standalone ASAR targets mapped to resource-relative .asar paths; stages sidecars and embeds header integrity."),
        "executable_name": attr.string(default = "electron"),
        "product_name": attr.string(),
        "app_id": attr.string(),
        "macos_protocols": attr.string_list_dict(doc = "macOS URL type names mapped to URI schemes; schemes normalize to lowercase."),
        "macos_protocol_roles": attr.string_dict(doc = "Role per macOS URL type: Editor (default), Viewer, Shell, QLGenerator or None."),
        "macos_icon": attr.label(allow_single_file = [".icns"], doc = "Declared ICNS asset, copied to Contents/Resources/app.icns before signing."),
        "build_version": attr.string(doc = "Native macOS/Windows build version; one to four decimal components. Overrides build_number for native metadata."),
        "build_number": attr.string(doc = "Explicit decimal build iteration; appends to numeric app version for native metadata. Default DEB revision unless overridden."),
        "macos_signer": attr.label(executable = True, allow_single_file = True, cfg = "exec", doc = "Execution-platform rcodesign; required on macOS. Ad hoc signing only."),
        "macos_entitlements": attr.label(allow_single_file = [".plist"], doc = "XML entitlements for the main macOS executable."),
        "macos_entitlements_inherit": attr.label(allow_single_file = [".plist"], doc = "XML entitlements for nested Mach-O executables, frameworks, libraries and addons."),
        "macos_hardened_runtime": attr.bool(default = False, doc = "Set the runtime code-signature flag on the main bundle and nested Mach-O files."),
        "windows_resource_tool": attr.label(providers = [ElectronWindowsResourceToolInfo], cfg = "exec", doc = "Declared PE resource editor; required for Windows embedded ASAR validation, metadata or icons."),
        "windows_metadata": attr.string_dict(doc = "Windows version strings: CompanyName, FileDescription, InternalName, LegalCopyright, OriginalFilename, ProductName."),
        "windows_icon": attr.label(allow_single_file = [".ico"], doc = "Declared ICO asset replacing executable icon groups through windows_resource_tool."),
        "remove_package_scripts": attr.bool(default = False),
        "fuses": attr.string_dict(doc = "Electron v1 fuse names mapped to on/off; macOS edits its framework before signing. See README."),
        "_assembler": attr.label(default = Label("//electron/private:assemble"), executable = True, cfg = "exec"),
        "_linux": attr.label(default = Label("@platforms//os:linux")),
        "_macos": attr.label(default = Label("@platforms//os:osx")),
        "_windows": attr.label(default = Label("@platforms//os:windows")),
    },
    doc = "Assemble a target-platform app using declared inputs and execution-platform tools.",
)
