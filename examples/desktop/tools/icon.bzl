"""Build the example's icon fixture on its execution platform."""

def _impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".icns")
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [output.path],
        outputs = [output],
        mnemonic = "ExampleIcns",
    )
    return [DefaultInfo(files = depset([output]))]

example_icns = rule(
    implementation = _impl,
    attrs = {"_writer": attr.label(default = Label("//tools:icon_writer"), executable = True, cfg = "exec")},
)
