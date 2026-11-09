# rules_electron

Native Bazel rules for Electron app assembly: Linux/Windows directories and macOS app ZIPs.

Current implementation assembles declared runtime files and app files into a
relocatable directory, with optional ASAR, unpacked native modules, extra resources
and Linux/Windows fuse settings. No electron-builder, package installation, network access,
GN or Ninja runs inside assembly actions. Python runs through a pinned Bazel
execution toolchain; the target runtime is never executed during assembly.

**Source runtime pending:** [formatjs/electron](https://github.com/formatjs/electron)
builds source components but does not yet link a complete Electron executable.
The [desktop example](examples/desktop/README.md) exercises real app behavior with
an explicitly labeled, pinned official bootstrap runtime. No source-built Electron
app launch is claimed. The Electron source module has not been published to BCR.

## Usage

Given a source-built Linux Electron executable and its complete runtime files:

```starlark
load("@rules_electron//electron:defs.bzl", "electron_app", "electron_runtime")

electron_runtime(
    name = "runtime",
    binary = ":source_built_electron",
    files = {
        ":icu_data": "icudtl.dat",
        ":english_locale": "locales/en-US.pak",
        # Declare every runtime dependency from the source build.
    },
)

electron_app(
    name = "app",
    runtime = ":runtime",
    package_json = "package.json",
    srcs = {
        "main.js": "main.js",
        "renderer/index.html": "renderer/index.html",
    },
)
```

Runtime mappings use single-file labels as keys. App `srcs` and `extra_resources`
also accept a single tree artifact per label, mapped beneath the destination path.
Paths must be normalized and relative. `package.json`'s `main` must name a declared
file exactly; missing `main` defaults to `index.js`. Bundle TypeScript/renderer
code with existing Bazel rules before assembly. Declare npm runtime files
explicitly; assembly does not resolve dependencies or rebuild native addons.

Output: `bazel-bin/<package>/app/`, executable `app/electron`, app content under
`app/resources/app/`. Set `executable_name` to rename the binary. Runtime adapters
must exclude `resources/app`, `resources/app.asar` and `resources/app.asar.unpacked`.
Modes normalize to 0755 for executables, 0644 otherwise; timestamps to epoch.
Setuid sandbox installation is outside this directory format.

Set `asar = True` for deterministic `resources/app.asar`; `asar_unpacked` lists
exact app-relative files stored alongside it. `extra_resources` maps files or
trees beneath `resources/`, outside the app archive. `extra_files` maps files or
trees beneath the distribution root, or `Contents/` on macOS; see
[file mappings](docs/file-mappings.md). Set `remove_package_scripts` to drop
development scripts from the packaged manifest. No implicit file filtering
or native-addon rebuilds occur.

`electron_asar` creates standalone archives. Map them with `extra_asars` to stage
unpacked sidecars and include their header digests in supported platform metadata;
see [ASAR integrity](docs/asar-integrity.md).

V1 `fuses` accepts `"on"`/`"off"` for `runAsNode`, `enableCookieEncryption`,
`enableNodeOptionsEnvironmentVariable`, `enableNodeCliInspectArguments`,
`enableEmbeddedAsarIntegrityValidation`, `onlyLoadAppFromAsar`,
`loadBrowserProcessSpecificV8Snapshot`, `grantFileProtocolExtraPrivileges` and
`wasmTrapHandlers`. Unspecified fuses
remain unchanged; missing/removed fuses fail. `onlyLoadAppFromAsar = "on"` requires
ASAR. macOS mutates the single-architecture framework before ad hoc signing.
macOS ASAR assembly embeds the raw JSON header's SHA-256 in `Info.plist`;
enable `enableEmbeddedAsarIntegrityValidation` and `onlyLoadAppFromAsar` together
to enforce it. Windows embeds the same hash in PE resources when a declared
`windows_resource_tool` is supplied. See [ASAR integrity](docs/asar-integrity.md)
and [Windows resources](docs/windows-resources.md).
[Declared ASAR links](docs/asar-links.md) support virtual file/directory aliases and linked entry points.
[Unpack patterns](docs/file-patterns.md) select sidecar files through declared minimatch tooling.
[File selection](docs/file-selection.md) filters declared trees before app/resource/ASAR mappings.
macOS bundle/helper metadata, ad hoc signing and
[URL scheme declarations](docs/macos-protocols.md) are supported.
[Declared ICNS icons](docs/macos-icons.md) apply to the main and helper bundles.
[Additional Info.plist fields](docs/macos-metadata.md) declare document types,
UTIs and other main-bundle metadata before signing.
[Declared ICO icons](docs/windows-resources.md#windows-icons) brand Windows executables.
macOS installers, release signing and broader OS integration remain pending. Linux DEB
packaging supplies desktop/MIME/protocol/icon metadata and declared package hooks;
see [Linux packages](docs/linux-packages.md).
Per-user Windows NSIS packaging supplies shortcuts, URI schemes and updater cache
seeding; see [Windows installers](docs/windows-installers.md).
Per-user file handlers: [Windows file associations](docs/windows-file-associations.md).
`electron_archive` creates deterministic ZIP/tar.gz releases with explicit
compression controls; see [release archives](docs/release-archives.md).

## Development

```sh
bazel test //...
bazel build --platforms=//platforms:linux_aarch64 //tests:app
bazel run @buildifier_prebuilt//:buildifier -- -mode=check -r .
```

`buildbuddy.yaml` follows
[rules_formatjs CI](https://github.com/formatjs/rules_formatjs/blob/main/buildbuddy.yaml):
Linux tests on BuildBuddy remote execution, native fixture cross-linking for Linux
x86_64/arm64, macOS x86_64/arm64 and Windows x86_64 (MinGW fixture). Linux assembly additionally
cross-builds for both architectures. Cross-linking does not prove native execution
or Electron support for those platforms. Runtime/build tools remain in target/exec
configurations respectively. Configure BuildBuddy credentials through CI settings
or `.bazelrc.user`; credentials do not belong in source.

The independent desktop workspace declares all seven target/compiler variants.
BB Linux workers compile all variants and emit four native-host smoke archives; GH hosted Linux x64,
macOS ARM64 and Windows x64/ARM64 jobs execute native smoke without building.
Linux ARM64 is cross-build only. macOS uses a pinned execution-platform rcodesign
for ad hoc signing and deterministic ZIP transport of framework symlinks. Runtime
ZIP adapters accept `archive`, optional `exclude_files`, and non-macOS `languages`.
See the [parity checklist](docs/packaging-parity.md) for remaining release work.

See [design](docs/architecture.md) for source integration and next milestones.
Build isolation and reproducibility gates are documented in [hermeticity](docs/hermeticity.md).
BB profiling and measured limits are tracked in [performance](docs/performance.md).

`electron_update_config` and `electron_update_feed` generate electron-updater
configuration, channel manifests, SHA-512 metadata and external blockmaps from
declared final artifacts. See [updater support](docs/updates.md) and the
[release parity plan](docs/release-plan.md). Linux DEB install/update smoke is
supported; release signing and other installer formats remain pending.

App version overrides and build iterations: [identity contract](docs/metadata.md).
Integrity-pinned npm inputs: [npm runtime trees](docs/npm.md).
macOS entitlement/hardening inputs: [signing settings](docs/macos-signing.md).

`electron_prepackaged_app` imports immutable app trees/macOS ZIPs for release
packaging, validating target CPU and packaged identity. See
[prepackaged apps](docs/prepackaged.md) for validation and signature scope.


Source-built Linux AppImage packaging and embedded updater maps are documented in
[AppImage](docs/appimage.md). Runtime extraction/launch and both Linux cross-builds
pass on BB; public packaging and installed updater lifecycle validation continue.
