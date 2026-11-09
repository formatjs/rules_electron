"""Build the example's icon fixture on its execution platform."""

def _impl(ctx):
    if ctx.attr.size < 1 or ctx.attr.size > 1024:
        fail("size must fit 1..1024")
    if ctx.attr.gray < 0 or ctx.attr.gray > 255:
        fail("gray must fit 0..255")
    output = ctx.actions.declare_file(ctx.label.name + "." + ctx.attr.format)
    ctx.actions.run(
        executable = ctx.executable._writer,
        arguments = [output.path, str(ctx.attr.gray), str(ctx.attr.size)],
        outputs = [output],
        mnemonic = "ExampleIcns",
    )
    return [DefaultInfo(files = depset([output]))]

example_icon = rule(
    implementation = _impl,
    attrs = {
        "format": attr.string(default = "icns", values = ["icns", "ico", "png"]),
        "gray": attr.int(default = 43),
        "size": attr.int(default = 32),
        "_writer": attr.label(default = Label("//tools:icon_writer"), executable = True, cfg = "exec"),
    },
)
