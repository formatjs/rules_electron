"""Build the source SDK archive under its declared target ABI."""

def _sdk_platform(settings, attr):
    _ = settings
    return {"//command_line_option:platforms": [str(attr.platform)]}

_sdk = transition(
    implementation = _sdk_platform,
    inputs = [],
    outputs = ["//command_line_option:platforms"],
)

def _impl(ctx):
    files = depset(transitive = [target[DefaultInfo].files for target in ctx.attr.srcs])
    if len(files.to_list()) != 1:
        fail("Expected one source runtime ZIP")
    return [DefaultInfo(files = files)]

source_runtime_archive = rule(
    implementation = _impl,
    attrs = {
        "srcs": attr.label_list(mandatory = True, allow_files = [".zip"], cfg = _sdk),
        "platform": attr.label(mandatory = True),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)
