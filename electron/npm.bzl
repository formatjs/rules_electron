"""Declared workspace packages and integrity-pinned npm runtime trees."""

load("//electron/private:npm_lock.bzl", "npm_lock_packages", "npm_package_path")
load(":files.bzl", "ElectronFileTreeInfo", "electron_files")

ElectronNpmPackageInfo = provider(
    doc = "A declared package tree and the normalized package manifest shipped inside it.",
    fields = {"package_json": "Normalized package JSON file.", "tree": "Package-root tree artifact."},
)

def npm_package_manifests(targets):
    """Get declared JSON files from package providers or single-file targets."""
    manifests = []
    for target in targets:
        if ElectronNpmPackageInfo in target:
            manifests.append(target[ElectronNpmPackageInfo].package_json)
        else:
            files = target[DefaultInfo].files.to_list()
            if len(files) != 1 or files[0].is_directory or not files[0].basename.endswith(".json"):
                fail("Expected a package provider or one JSON file: " + str(target.label))
            manifests.append(files[0])
    return manifests

def _package_impl(ctx):
    entries, inputs = [], [ctx.file.package_json]
    dependencies = npm_package_manifests(ctx.attr.dependency_manifests)
    inputs += dependencies
    for target, destination in ctx.attr.srcs.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Each package mapping requires one file or tree artifact")
        file = files[0]
        entry = {"source": file.path, "path": destination, "directory": file.is_directory}
        inputs.append(file)
        if ElectronFileTreeInfo in target:
            directories = target[ElectronFileTreeInfo].directory_manifest
            inputs.append(directories)
            entry["directory_manifest"] = directories.path
        entries.append(entry)
    output = ctx.actions.declare_directory(ctx.label.name)
    package = ctx.actions.declare_file(ctx.label.name + ".package.json")
    directories = ctx.actions.declare_file(ctx.label.name + ".directories.json")
    manifest = ctx.actions.declare_file(ctx.label.name + ".inputs.json")
    ctx.actions.write(manifest, json.encode({
        "source": ctx.file.package_json.path,
        "entries": entries,
        "dependency_manifests": [file.path for file in dependencies],
        "remove_scripts": ctx.attr.remove_scripts,
    }))
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [manifest.path, output.path, package.path, directories.path],
        inputs = inputs + [manifest],
        outputs = [output, package, directories],
        mnemonic = "ElectronNpmPackage",
    )
    return [
        DefaultInfo(files = depset([output])),
        ElectronNpmPackageInfo(package_json = package, tree = output),
        ElectronFileTreeInfo(directory_manifest = directories),
        OutputGroupInfo(package_json = depset([package])),
    ]

electron_npm_package = rule(
    implementation = _package_impl,
    attrs = {
        "package_json": attr.label(mandatory = True, allow_single_file = [".json"]),
        "srcs": attr.label_keyed_string_dict(allow_files = True, doc = "Declared files/trees mapped beneath the package root. package.json is supplied separately."),
        "dependency_manifests": attr.label_list(allow_files = [".json"], doc = "Package providers or declared JSON files supplying exact production dependency versions."),
        "remove_scripts": attr.bool(default = False),
        "_writer": attr.label(default = Label("//electron/private:npm_package"), executable = True, cfg = "exec"),
    },
    doc = "Package workspace/generated files without resolving dependencies or running lifecycle scripts.",
)

def electron_npm_tree(name, packages, strip_node_modules = True, **kwargs):
    """Compose explicitly selected package trees at their Node installation paths."""
    mappings = {}
    for target, path in packages.items():
        error = npm_package_path(path)
        if error:
            fail(error)
        mappings[target] = path[len("node_modules/"):] if strip_node_modules else path
    electron_files(name = name, srcs = mappings, **kwargs)

def _impl(ctx):
    selection = npm_lock_packages(
        json.decode(ctx.read(ctx.attr.lock)),
        include_dev = ctx.attr.include_dev,
        target_os = ctx.attr.target_os,
        target_cpu = ctx.attr.target_cpu,
        target_libc = ctx.attr.target_libc,
    )
    if selection.error:
        fail(selection.error)
    for path, package in selection.packages.items():
        ctx.download_and_extract(
            url = package["resolved"],
            integrity = package["integrity"],
            output = path,
            stripPrefix = "package",
        )
    ctx.file("BUILD.bazel", """load("@rules_electron//electron:files.bzl", "electron_files")
electron_files(
    name = "runtime",
    srcs = {path: path[%d:] for path in glob(["node_modules/**"], exclude = ["**/BUILD", "**/BUILD.bazel"])},
    visibility = ["//visibility:public"],
)
""" % (len("node_modules/") if ctx.attr.strip_node_modules else 0))

npm_runtime = repository_rule(
    implementation = _impl,
    attrs = {
        "lock": attr.label(mandatory = True, allow_single_file = [".json"]),
        "include_dev": attr.bool(default = False, doc = "Include packages marked dev in the lockfile."),
        "strip_node_modules": attr.bool(default = True, doc = "Expose node_modules contents at the tree root for app mapping."),
        "target_os": attr.string(doc = "Explicit npm OS name, such as linux, darwin or win32. Required for constrained packages."),
        "target_cpu": attr.string(doc = "Explicit npm CPU name, such as x64 or arm64. Required for constrained packages."),
        "target_libc": attr.string(doc = "Explicit npm libc name, such as glibc or musl. Required for constrained packages."),
    },
    doc = "Fetch an npm lockfile v3 dependency tree. No dependency resolution, lifecycle scripts or host platform discovery.",
)
