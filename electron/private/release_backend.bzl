"""Stable runfiles path for the declared release signer."""

def _impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(output = output, target_file = ctx.executable.tool, is_executable = True)
    return [DefaultInfo(
        files = depset([output]),
        runfiles = ctx.runfiles(files = [output]).merge(ctx.attr.tool[DefaultInfo].default_runfiles),
    )]

release_backend = rule(
    implementation = _impl,
    attrs = {"tool": attr.label(executable = True, cfg = "exec", mandatory = True)},
)
