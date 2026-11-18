"""ZIP handoffs whose compressed bytes remain cacheable below CAS blob limits."""

def _compress_impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".parts")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(manifest, json.encode({
        "sources": [{"source": f.path, "prefix": f.basename, "directory": f.is_directory} for f in ctx.files.srcs],
        "platform": ctx.attr.platform,
        "compression_level": ctx.attr.compression_level,
    }))
    ctx.actions.run(
        executable = ctx.executable._zip,
        arguments = ["compress", manifest.path, output.path],
        inputs = [manifest] + ctx.files.srcs,
        outputs = [output],
        mnemonic = "ElectronZipCompress",
        progress_message = "Compressing cacheable ZIP pieces %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

def _assemble_impl(ctx):
    ctx.actions.run(
        executable = ctx.executable._zip,
        arguments = ["assemble", ctx.file.parts.path, ctx.outputs.out.path],
        inputs = [ctx.file.parts],
        outputs = [ctx.outputs.out],
        mnemonic = "ElectronZipAssemble",
        progress_message = "Assembling ZIP %{label}",
    )
    return [DefaultInfo(files = depset([ctx.outputs.out]))]

_zip_tool = attr.label(default = Label("//electron/private:zip_parts_tool"), executable = True, cfg = "exec")

_compress = rule(
    implementation = _compress_impl,
    attrs = {
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "platform": attr.string(mandatory = True, values = ["linux", "macos", "windows"]),
        "compression_level": attr.int(default = 6, values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
        "_zip": _zip_tool,
    },
)

_assemble = rule(
    implementation = _assemble_impl,
    attrs = {
        "parts": attr.label(mandatory = True, allow_single_file = True),
        "out": attr.output(mandatory = True),
        "_zip": _zip_tool,
    },
)

def electron_zip(name, srcs, platform, out = None, compression_level = 6, **kwargs):
    """Archive files and trees under their basenames; cache 64MiB compressed pieces."""
    _compress(
        name = name + "_compressed",
        srcs = srcs,
        platform = platform,
        compression_level = compression_level,
        **kwargs
    )
    _assemble(name = name, parts = ":" + name + "_compressed", out = out or name + ".zip", **kwargs)
