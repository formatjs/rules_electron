"""BB-built native smoke shards; all seven target variants remain checked."""

load("@rules_electron//electron:defs.bzl", "ElectronAppInfo")

_VARIANTS = [
    "linux_x86_64",
    "linux_aarch64",
    "macos_aarch64",
    "windows_x86_64_gnullvm",
    "windows_aarch64_gnullvm",
    "windows_x86_64_msvc",
    "windows_aarch64_msvc",
]

_SHARDS = {
    "linux-x64": ["linux_x86_64"],
    "macos-arm64": ["macos_aarch64"],
    "windows-x64": ["windows_x86_64_gnullvm", "windows_x86_64_msvc"],
    "windows-arm64": ["windows_aarch64_gnullvm", "windows_aarch64_msvc"],
}

_SHARDED_VARIANTS = {variant: True for variants in _SHARDS.values() for variant in variants}

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

def _windows_split(settings, attr):
    return {name: value for name, value in _split(settings, attr).items() if name.endswith("_msvc")}

_windows_targets = transition(
    implementation = _windows_split,
    inputs = ["//command_line_option:features"],
    outputs = ["//command_line_option:platforms", "//command_line_option:features"],
)

def _windows_runtime_split(settings, attr):
    return {name: value for name, value in _split(settings, attr).items() if name.startswith("windows_")}

_windows_runtime_targets = transition(
    implementation = _windows_runtime_split,
    inputs = ["//command_line_option:features"],
    outputs = ["//command_line_option:platforms", "//command_line_option:features"],
)

def _impl(ctx):
    inputs = {variant: [] for variant in _VARIANTS}
    validation_inputs = []
    entries = []
    for variant, target in ctx.split_attr.app.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Expected one app output")
        file = files[0]
        inputs[variant].append(file)
        validation_inputs.append(file)
        entry = {"variant": variant, "source": file.path, "directory": file.is_directory}
        directories = getattr(target[ElectronAppInfo], "directory_manifest", None) if ElectronAppInfo in target else None
        if directories:
            inputs[variant].append(directories)
            entry["directory_manifest"] = directories.path
        entries.append(entry)
    for targets in [ctx.split_attr.linux_packages, ctx.split_attr.windows_packages, ctx.split_attr.windows_runtime_tools]:
        for variant, target in targets.items():
            for file in target[DefaultInfo].files.to_list():
                inputs[variant].append(file)

                # Keep build-only package generation in the matrix.
                if variant not in _SHARDED_VARIANTS:
                    validation_inputs.append(file)
                entries.append({"variant": variant, "source": file.path, "directory": file.is_directory, "package": True})
    manifest = ctx.actions.declare_file(ctx.label.name + ".validation.json")
    validation = ctx.actions.declare_file(ctx.label.name + ".validated")
    outputs = {
        shard: ctx.actions.declare_file("electron-smoke-" + shard + ".zip")
        for shard in _SHARDS
    }
    ctx.actions.write(manifest, json.encode({
        "mode": "validate",
        "entries": entries,
        "output": validation.path,
    }))
    ctx.actions.run(
        executable = ctx.executable._bundle,
        arguments = [manifest.path],
        inputs = validation_inputs + [manifest],
        outputs = [validation],
        mnemonic = "ElectronCrossSmokeValidate",
    )
    for shard, variants in _SHARDS.items():
        shard_manifest = ctx.actions.declare_file(ctx.label.name + "." + shard + ".json")
        ctx.actions.write(shard_manifest, json.encode({
            "mode": "shard",
            "entries": [entry for entry in entries if entry["variant"] in variants],
            "output": outputs[shard].path,
            "shard": shard,
            "validation": validation.path,
        }))
        ctx.actions.run(
            executable = ctx.executable._bundle,
            arguments = [shard_manifest.path],
            inputs = [shard_manifest, validation] + [file for variant in variants for file in inputs[variant]],
            outputs = [outputs[shard]],
            mnemonic = "ElectronCrossSmokeBundle",
            progress_message = "Packing native smoke " + shard,
        )
    return [DefaultInfo(files = depset(outputs.values()))]

cross_smoke_bundle = rule(
    implementation = _impl,
    attrs = {
        "app": attr.label(mandatory = True, cfg = _targets),
        "linux_packages": attr.label(mandatory = True, cfg = _linux_targets),
        "windows_packages": attr.label(mandatory = True, cfg = _windows_targets),
        "windows_runtime_tools": attr.label(mandatory = True, cfg = _windows_runtime_targets),
        "_bundle": attr.label(default = Label("//tools:bundle"), executable = True, cfg = "exec"),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)
