"""Compile Node/V8 addons against an explicit Electron header/import SDK."""

load("@rules_cc//cc:cc_binary.bzl", "cc_binary")

_RUNTIME_STAGE = str(Label("@llvm//toolchain:runtime_stage"))

def _abi(settings, attr):
    platforms = settings["//command_line_option:platforms"]
    features = settings["//command_line_option:features"]
    if attr.windows_platform:
        platforms = [str(attr.windows_platform)]
        features = [f for f in features if f not in ["static_link_msvcrt", "dynamic_link_msvcrt", "-dynamic_link_msvcrt"]]
        features += ["-dynamic_link_msvcrt", "static_link_msvcrt"]
    return {
        "//command_line_option:platforms": platforms,
        "//command_line_option:features": features,
        _RUNTIME_STAGE: "stage1_hosted" if attr.sdk_cxxstdlib else settings[_RUNTIME_STAGE],
    }

_electron_abi = transition(
    implementation = _abi,
    inputs = ["//command_line_option:platforms", "//command_line_option:features", _RUNTIME_STAGE],
    outputs = ["//command_line_option:platforms", "//command_line_option:features", _RUNTIME_STAGE],
)

def _impl(ctx):
    files = depset(transitive = [target[DefaultInfo].files for target in ctx.attr.srcs])
    if len(files.to_list()) != 1:
        fail("Expected one native addon library")
    return [DefaultInfo(files = files)]

_addon = rule(
    implementation = _impl,
    attrs = {
        "srcs": attr.label_list(cfg = _electron_abi),
        "windows_platform": attr.label(),
        "sdk_cxxstdlib": attr.bool(),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)

def electron_cc_addon(name, srcs, headers, deps = [], copts = [], defines = [], linkopts = [], sdk_cxxstdlib = False, visibility = None, tags = []):
    """Build an addon; Windows uses Electron's MSVC ABI regardless of app compiler."""
    if not any([d == "NODE_GYP_MODULE_NAME" or d.startswith("NODE_GYP_MODULE_NAME=") for d in defines]):
        identifier = "electron_" + "".join([name[i] if name[i] in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" else "_" for i in range(len(name))])
        defines = ["NODE_GYP_MODULE_NAME=" + identifier] + defines
    windows = name + "_windows"
    macos = name + "_macos"
    native.config_setting(name = windows, constraint_values = ["@platforms//os:windows"])
    native.config_setting(name = macos, constraint_values = ["@platforms//os:osx"])
    for cpu in ["x86_64", "aarch64"]:
        native.config_setting(
            name = windows + "_" + cpu,
            constraint_values = ["@platforms//os:windows", "@platforms//cpu:" + cpu],
        )
    cc_binary(
        name = name + "_unix.node",
        srcs = srcs,
        deps = [headers] + deps,
        copts = ["-std=c++20"] + (["-nostdinc++"] if sdk_cxxstdlib else []) + copts,
        defines = defines,
        linkopts = select({":" + macos: ["-Wl,-undefined,dynamic_lookup"], "//conditions:default": []}) + (["-nostdlib++"] if sdk_cxxstdlib else []) + linkopts,
        linkshared = True,
        target_compatible_with = select({":" + windows: ["@platforms//:incompatible"], "//conditions:default": []}),
        visibility = ["//visibility:private"],
        tags = tags,
    )
    cc_binary(
        name = name + "_windows.dll",
        srcs = srcs + [Label("//electron/private:node_delay_load.cc")],
        deps = [headers, Label("//third_party:node_delay_import")] + deps,
        copts = ["/std:c++20"] + copts,
        defines = defines,
        linkopts = ["/delayload:node.exe"] + linkopts,
        linkshared = True,
        target_compatible_with = ["@platforms//os:windows", "@llvm//constraints/windows/abi:msvc"],
        visibility = ["//visibility:private"],
        tags = tags,
    )
    _addon(
        name = name,
        sdk_cxxstdlib = sdk_cxxstdlib,
        srcs = select({":" + windows: [":" + name + "_windows.dll"], "//conditions:default": [":" + name + "_unix.node"]}),
        windows_platform = select({
            ":" + windows + "_x86_64": "@llvm//platforms:windows_x86_64_msvc",
            ":" + windows + "_aarch64": "@llvm//platforms:windows_aarch64_msvc",
            "//conditions:default": None,
        }),
        visibility = visibility,
        tags = tags,
    )
