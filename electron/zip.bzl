"""ZIP handoffs whose compressed bytes remain cacheable below CAS blob limits."""

_ZipPartsInfo = provider(fields = ["layout"])

def _path(file):
    return file.path

def _member_action(template_ctx, tool, output, sources, inputs, level):
    arguments = template_ctx.args()
    arguments.add_all(["member", json.encode(sources), output.path, str(level)])
    arguments.set_param_file_format("multiline")
    arguments.use_param_file("@%s", use_always = True)
    template_ctx.run(
        executable = tool,
        tools = [tool],
        arguments = [arguments],
        inputs = inputs,
        outputs = [output],
        progress_message = "Compressing ZIP members " + output.short_path,
    )

def _map_members(template_ctx, *, input_directories, output_directories, tools, additional_inputs, additional_params):
    small = []
    small_inputs = []
    output = output_directories["parts"]
    for key, directory in input_directories.items():
        prefix = additional_params["prefix_" + key]
        root = additional_params["path_" + key] + "/"
        for file in sorted(directory.files, key = _path):
            path = file.path.removeprefix(root)
            source = {"source": file.path, "prefix": prefix + "/" + path, "directory": False}
            if file.extension.lower() in ["exe", "dll", "pak", "asar", "bin", "dat", "node"]:
                member = template_ctx.declare_file(key + "/" + path + ".zip", directory = output)
                _member_action(template_ctx, tools["zip"], member, [source], [file], additional_params["level"])
            else:
                small.append(source)
                small_inputs.append(file)
    for file in additional_inputs.values():
        small.append({"source": file.path, "prefix": file.basename, "directory": False})
        small_inputs.append(file)
    small_output = template_ctx.declare_file("small.zip", directory = output)
    _member_action(template_ctx, tools["zip"], small_output, small, small_inputs, additional_params["level"])

def _compress_impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".parts")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(manifest, json.encode({
        "sources": [{"source": f.path, "prefix": f.basename, "directory": f.is_directory} for f in ctx.files.srcs],
        "platform": ctx.attr.platform,
        "compression_level": ctx.attr.compression_level,
    }))
    directories = {"source" + str(i): f for i, f in enumerate(ctx.files.srcs) if f.is_directory}
    if ctx.attr.incremental and directories:
        if ctx.attr.platform != "windows":
            fail("Incremental ZIP mode requires Windows trees without semantic symlinks")
        layout = ctx.actions.declare_file(ctx.label.name + ".layout.json")
        ctx.actions.run(
            executable = ctx.executable._zip,
            arguments = ["layout", manifest.path, layout.path],
            inputs = [manifest] + ctx.files.srcs,
            outputs = [layout],
            mnemonic = "ElectronZipLayout",
        )
        params = {"level": ctx.attr.compression_level}
        for key, directory in directories.items():
            params["prefix_" + key] = directory.basename
            params["path_" + key] = directory.path
        ctx.actions.map_directory(
            input_directories = directories,
            additional_inputs = {"file" + str(i): f for i, f in enumerate(ctx.files.srcs) if not f.is_directory},
            output_directories = {"parts": output},
            tools = {"zip": ctx.attr._zip[DefaultInfo].files_to_run},
            additional_params = params,
            mnemonic = "ElectronZipMember",
            implementation = _map_members,
        )
        return [DefaultInfo(files = depset([output])), _ZipPartsInfo(layout = layout)]
    ctx.actions.run(
        executable = ctx.executable._zip,
        arguments = ["compress", manifest.path, output.path],
        inputs = [manifest] + ctx.files.srcs,
        outputs = [output],
        mnemonic = "ElectronZipCompress",
        progress_message = "Compressing cacheable ZIP pieces %{label}",
    )
    return [DefaultInfo(files = depset([output])), _ZipPartsInfo(layout = None)]

def _assemble_impl(ctx):
    layout = ctx.attr.parts[_ZipPartsInfo].layout
    ctx.actions.run(
        executable = ctx.executable._zip,
        arguments = (["merge", ctx.file.parts.path, layout.path, ctx.outputs.out.path] if layout else ["assemble", ctx.file.parts.path, ctx.outputs.out.path]),
        inputs = [ctx.file.parts] + ([layout] if layout else []),
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
        "incremental": attr.bool(),
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

def electron_zip(name, srcs, platform, out = None, compression_level = 6, incremental = False, **kwargs):
    """Archive files and trees under their basenames; cache 64MiB compressed pieces."""
    _compress(
        name = name + "_compressed",
        srcs = srcs,
        platform = platform,
        compression_level = compression_level,
        incremental = incremental,
        **kwargs
    )
    _assemble(name = name, parts = ":" + name + "_compressed", out = out or name + ".zip", **kwargs)
