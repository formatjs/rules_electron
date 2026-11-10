"""Select both Windows MSVC package variants for one architecture-neutral bundle."""

def _split(settings, attr):
    _ = attr
    features = [value for value in settings["//command_line_option:features"] if value not in ["static_link_msvcrt", "dynamic_link_msvcrt", "-dynamic_link_msvcrt"]]
    return {
        cpu: {
            "//command_line_option:platforms": ["//platforms:windows_" + cpu + "_msvc"],
            "//command_line_option:features": features + ["-dynamic_link_msvcrt", "static_link_msvcrt"],
        }
        for cpu in ["x86_64", "aarch64"]
    }

_targets = transition(
    implementation = _split,
    inputs = ["//command_line_option:features"],
    outputs = ["//command_line_option:platforms", "//command_line_option:features"],
)

def _impl(ctx):
    if sorted(ctx.split_attr.src) != ["aarch64", "x86_64"]:
        fail("Bundle fixture requires both native Windows CPUs")
    return [DefaultInfo(files = depset(transitive = [target[DefaultInfo].files for target in ctx.split_attr.src.values()]))]

msix_bundle_inputs = rule(
    implementation = _impl,
    attrs = {
        "src": attr.label(mandatory = True, cfg = _targets),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)
