"""Build the example's icon fixture on its execution platform."""

def _impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + "." + ctx.attr.format)
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [output.path],
        outputs = [output],
        mnemonic = "ExampleIcns",
    )
    return [DefaultInfo(files = depset([output]))]

example_icon = rule(
    implementation = _impl,
    attrs = {
        "format": attr.string(default = "icns", values = ["icns", "ico"]),
        "_writer": attr.label(default = Label("//tools:icon_writer"), executable = True, cfg = "exec"),
    },
)
