"""Exercise command-size limits through real directory action templates."""

def _impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.run(
        executable = ctx.executable._tool,
        arguments = [output.path],
        outputs = [output],
        mnemonic = "ZipTreeFixture",
    )
    return [DefaultInfo(files = depset([output]))]

zip_tree_fixture = rule(
    implementation = _impl,
    attrs = {"_tool": attr.label(default = Label("//tests:zip_tree_fixture_tool"), executable = True, cfg = "exec")},
)
