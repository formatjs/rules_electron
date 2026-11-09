"""Static PIE runtime without changing application compilation settings."""

load("@rules_cc//cc:cc_binary.bzl", "cc_binary")

def _runtime_platform(settings, attr):
    _ = settings, attr
    return {
        "//command_line_option:force_pic": True,
        "//command_line_option:platforms": [str(Label("@llvm//platforms:linux_" + attr.architecture + "_musl"))],
    }

_runtime_transition = transition(
    implementation = _runtime_platform,
    inputs = [],
    outputs = ["//command_line_option:force_pic", "//command_line_option:platforms"],
)

def _runtime_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(output = output, target_file = ctx.executable.binary, is_executable = True)
    return [DefaultInfo(executable = output, runfiles = ctx.attr.binary[0][DefaultInfo].default_runfiles)]

_runtime = rule(
    implementation = _runtime_impl,
    executable = True,
    attrs = {
        "binary": attr.label(mandatory = True, executable = True, cfg = _runtime_transition),
        "architecture": attr.string(mandatory = True),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)

def static_pie_runtime(name, **kwargs):
    cc_binary(name = name + "_native", **kwargs)
    _runtime(
        name = name,
        binary = ":" + name + "_native",
        architecture = select({
            "@platforms//cpu:x86_64": "x86_64",
            "@platforms//cpu:aarch64": "aarch64",
        }),
        target_compatible_with = ["@platforms//os:linux"],
    )
