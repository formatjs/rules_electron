"""Cross-link fixtures in one analysis graph; target programs never execute."""

def _all(settings, attr):
    _ = settings, attr
    return {
        name: {"//command_line_option:platforms": ["//platforms:" + name]}
        for name in ["linux_x86_64", "linux_aarch64", "macos_x86_64", "macos_aarch64", "windows_x86_64"]
    }

def _linux(settings, attr):
    return {name: values for name, values in _all(settings, attr).items() if name.startswith("linux_")}

_all_platforms = transition(implementation = _all, inputs = [], outputs = ["//command_line_option:platforms"])
_linux_platforms = transition(implementation = _linux, inputs = [], outputs = ["//command_line_option:platforms"])

def _impl(ctx):
    targets = list(ctx.split_attr.probe.values()) + list(ctx.split_attr.app.values())
    return [DefaultInfo(files = depset(transitive = [target[DefaultInfo].files for target in targets]))]

cross_build = rule(
    implementation = _impl,
    attrs = {
        "probe": attr.label(mandatory = True, cfg = _all_platforms),
        "app": attr.label(mandatory = True, cfg = _linux_platforms),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)
