# Windows resources

Declare an execution-platform Node and a pinned module tree containing
`node_modules/resedit` and its `pe-library` dependency:

```starlark
load("@rules_electron//electron:windows.bzl", "electron_windows_resource_tool")

electron_windows_resource_tool(
    name = "windows_resources",
    node = "@nodejs_26_13_0//:node",
    modules = ":pinned_resource_modules",
)
```

For Windows `electron_app` targets, set `windows_resource_tool` to that target.
`windows_metadata` accepts `CompanyName`, `FileDescription`, `InternalName`,
`LegalCopyright`, `OriginalFilename` and `ProductName` string overrides. Default
product/description/internal/filename strings follow the app identity. Other
existing strings remain unchanged unless overridden.

Fixed file/product versions use the package SemVer's three numeric components
plus a zero revision; each component must fit 0..65535. String versions retain
the full SemVer, including prerelease/build suffixes. The tool requires one
existing version resource and one language translation; unusual runtimes fail
rather than losing metadata silently.

With ASAR enabled, the editor also embeds the raw JSON header's SHA-256 in
`INTEGRITY` / `ELECTRONASAR`, using
[Electron's Windows resource contract](https://www.electronjs.org/docs/latest/tutorial/asar-integrity#windows).
Enable `enableEmbeddedAsarIntegrityValidation` and `onlyLoadAppFromAsar` to enforce
the digest. Existing integrity entries are replaced. Resource editing removes
the old runtime signature, then fuse mutation runs; release Authenticode must
follow both changes. This rule does not supply release signing credentials.

The desktop example pins `resedit` 3.1.0 and `pe-library` 2.0.1 through an npm
lockfile; no lifecycle scripts or package manager run in build actions. The
declared Node is built from
[hermeticbuild/nodejs](https://github.com/hermeticbuild/nodejs) 26.13.0 sources on
BB Linux workers. Its Temporal crate mapping is injected explicitly into the
Node extension. It remains an execution tool: the example's bootstrap Electron
39 runtime still embeds Node 22.20.0.

The source Node and LLVM/Rust toolchains are example dependencies. Consumers
that do not request Windows resource editing do not need that tool dependency.
Native x64/ARM64 Windows hosts execute BB outputs; they never build the editor
or apps. Smoke checks both compiler variants, reads resources through Windows
APIs and requires Electron to reject header and payload corruption.

The [hosted validation](https://github.com/formatjs/rules_electron/actions/runs/42347096977)
passed Windows x64/ARM64 metadata, launch and both corruption checks for GNU LLVM
and MSVC variants. Linux DEB install/update and macOS integrity smoke also passed.
This proves the source-built execution tool path against bootstrap Electron;
full source-built target Electron remains pending.

## Windows icons

Set `electron_app.windows_icon` to a declared `.ico` asset and supply
`windows_resource_tool`. Assembly validates the ICO directory and image ranges;
the pinned `resedit` tool replaces each existing executable icon group, retaining
its identifier and language. Icon edits precede release signing. No host image
utility or target executable runs during cross-compilation.

Supply valid ICO image representations; framing validation does not decode them.
The generic example generates PNG-backed icons with declared Python, then uses
`ExtractIconExW` and `GetDIBits` to check executable icon pixels.
[Native smoke](https://github.com/formatjs/rules_electron/actions/runs/42459477459)
passed x64/ARM64 with GNU LLVM and MSVC, including installed app paths.
Installer/uninstaller icon customization remains separate.
