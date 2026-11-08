"""Generated tree fixture crossing real action and remote-cache boundaries."""

load("//electron:files.bzl", "ElectronFileTreeInfo")

def _impl(ctx):
    python = ctx.toolchains["@rules_python//python:toolchain_type"].py3_runtime
    if not python.interpreter:
        fail("Fixture requires a declared Python interpreter")
    output = ctx.actions.declare_directory(ctx.label.name)
    directories = ctx.actions.declare_file(ctx.label.name + ".directories.json")
    ctx.actions.run(
        executable = python.interpreter,
        arguments = ["-I", "-B", ctx.file._script.path, output.path, directories.path],
        inputs = depset([ctx.file._script], transitive = [python.files] if python.files else []),
        outputs = [output, directories],
        env = {"PATH": "", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        mnemonic = "EmptyDirectoryFixture",
    )
    return [DefaultInfo(files = depset([output])), ElectronFileTreeInfo(directory_manifest = directories)]

empty_tree = rule(
    implementation = _impl,
    attrs = {"_script": attr.label(default = Label("//tests:empty_tree.py"), allow_single_file = True)},
    toolchains = ["@rules_python//python:toolchain_type"],
)
