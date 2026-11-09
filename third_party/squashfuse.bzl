"""Declared Squashfuse metadata generation."""

def _swap_impl(ctx):
    ctx.actions.run(
        executable = ctx.executable._generator,
        arguments = [ctx.file.header.path, ctx.file.upstream.path, ctx.outputs.header.path, ctx.outputs.source.path],
        inputs = [ctx.file.header, ctx.file.upstream],
        outputs = [ctx.outputs.header, ctx.outputs.source],
        mnemonic = "SquashfuseSwapIncludes",
    )

squashfuse_swap = rule(
    implementation = _swap_impl,
    attrs = {
        "header": attr.label(mandatory = True, allow_single_file = True),
        "upstream": attr.label(mandatory = True, allow_single_file = True),
        "_generator": attr.label(default = Label("//third_party:squashfuse_swap"), executable = True, cfg = "exec"),
    },
    outputs = {"header": "swap.h.inc", "source": "swap.c.inc"},
)
