"""One BB artifact containing all target variants; no target binaries execute."""

_VARIANTS = [
    "linux_x86_64",
    "linux_aarch64",
    "macos_aarch64",
    "windows_x86_64_gnullvm",
    "windows_aarch64_gnullvm",
    "windows_x86_64_msvc",
    "windows_aarch64_msvc",
]

def _split(settings, attr):
    _ = attr
    features = [f for f in settings["//command_line_option:features"] if f not in ["static_link_msvcrt", "dynamic_link_msvcrt", "-dynamic_link_msvcrt"]]
    return {
        name: {
            "//command_line_option:platforms": ["//platforms:" + name],
            "//command_line_option:features": features + (["-dynamic_link_msvcrt", "static_link_msvcrt"] if name.endswith("_msvc") else []),
        }
        for name in _VARIANTS
    }

_targets = transition(
    implementation = _split,
    inputs = ["//command_line_option:features"],
    outputs = ["//command_line_option:platforms", "//command_line_option:features"],
)

def _linux_split(settings, attr):
    _ = settings, attr
    return {
        name: {"//command_line_option:platforms": ["//platforms:" + name]}
        for name in ["linux_x86_64", "linux_aarch64"]
    }

_linux_targets = transition(
    implementation = _linux_split,
    inputs = [],
    outputs = ["//command_line_option:platforms"],
)

def _impl(ctx):
    inputs = []
    entries = []
    for variant, target in ctx.split_attr.app.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Expected one app output")
        file = files[0]
        inputs.append(file)
        entries.append({"variant": variant, "source": file.path, "directory": file.is_directory})
    for variant, target in ctx.split_attr.linux_packages.items():
        for file in target[DefaultInfo].files.to_list():
            inputs.append(file)
            entries.append({"variant": variant, "source": file.path, "directory": file.is_directory, "package": True})
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(manifest, json.encode(entries))
    output = ctx.actions.declare_file("electron-cross-smoke.zip")
    ctx.actions.run(
        executable = ctx.executable._bundle,
        arguments = [manifest.path, output.path],
        inputs = inputs + [manifest],
        outputs = [output],
        mnemonic = "ElectronCrossSmokeBundle",
    )
    return [DefaultInfo(files = depset([output]))]

cross_smoke_bundle = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, cfg = _targets),
        "linux_packages": attr.label(mandatory = True, cfg = _linux_targets),
        "_bundle": attr.label(default = Label("//tools:bundle"), executable = True, cfg = "exec"),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)
