# Desktop packaging migration example

Independent consumer, written from scratch. Main/preload/renderer, generated
bundle directory, stable Node-API addon, native helper, extra resources and ASAR.
No private application code or configuration belongs here.

## Build matrix

All compiler, generator, assembly and ad hoc signing actions run on BB Linux
x86_64 workers. One split-transition target produces all seven variants:

| Target | Native smoke host |
| --- | --- |
| Linux x86_64 GNU | GH Ubuntu x64 |
| Linux ARM64 GNU | Cross-build only |
| macOS ARM64 | GH macOS ARM64 |
| Windows x86_64 GNU LLVM | GH Windows x64 |
| Windows ARM64 GNU LLVM | GH Windows ARM64 |
| Windows x86_64 MSVC | GH Windows x64 |
| Windows ARM64 MSVC | GH Windows ARM64 |

The hosted BB workflow runs this from the example workspace:

```sh
bazel build --config=bb-workflow --config=msvc-license --lockfile_mode=error //:cross_build_smoke_bundle
```

MSVC configuration acknowledges the Visual Studio runtime license and must only
run on licensed hosts. Target transitions select static CRT and disable the
default dynamic CRT feature for MSVC variants. Before emitting any smoke archive,
the BB action checks runtime, addon and helper architectures for all seven apps,
including Linux ARM64 without a native host.

**Temporary bootstrap:** official Electron 39.0.0 distributions are SHA256-pinned
test runtimes, not source-built Electron or a production release recommendation.
Replace `:runtime` with source-built `electron_runtime` outputs once the overlay
runtime is integrated here. The overlay's standalone Linux x64 source runtime
now passes browser/renderer/IPC and ASAR smoke. Core rules never download Electron
themselves.

The BB `Source-built desktop example` workflow reuses this entire fixture in an
ignored sibling workspace. It replaces Linux x64's runtime with the pinned
source ZIP; other six variants retain explicit bootstrap runtimes. A producer
transition selects the Chromium SDK ABI without changing app/addon targets.
Dependency analysis requires the source runtime and rejects Linux x64 bootstrap
dependencies before building the usual four native smoke shards. This integration
is pending hosted validation.

The workflow triggers on `codex/source-example-ci`, so ordinary packaging pushes
do not rebuild Chromium. Push a reviewed main commit to that branch to run it:

```sh
git push origin main:codex/source-example-ci
```

All builds stay on BB; successful source-example status uses the same verified
artifact handoff and matching native smoke hosts. Its generated module lock is
retained as a BB artifact while the combined dependency graph stabilizes.

Linux and Windows produce directory artifacts, with executable `sample-desktop`
or `sample-desktop.exe`. macOS produces `app.zip` containing `Sample Desktop.app`.
Its Info.plist/helper names are adapted, framework symlinks preserved, then a
pinned Linux rcodesign execution tool re-signs the bundle ad hoc. ZIP transport
preserves symlink topology across remote artifact storage. Ad hoc signing is
separate from Developer ID release signing/notarization.
The macOS smoke handoff uses `:release_zip`, built by `electron_archive` with
compression level 1. Its native job checks signatures after release archival.
See [release archives](../../docs/release-archives.md).

Windows addon code resolves stable Node-API exports from the current executable,
so renaming Electron does not introduce a `node.exe` import dependency. This is a
small example addon, not a general native-addon rebuild toolchain. Addons using
Node/V8 internals still need Electron-specific headers, flags and ABI handling.

## Native smoke handoff

BB publishes `electron-smoke-{linux-x64,macos-arm64,windows-x64,windows-arm64}.zip`.
Each native job downloads only its host's archive. Both Windows compiler variants
and that CPU's installers share one archive. Linux ARM64 apps/packages remain
declared cross-build inputs but are omitted from native transport.
The GH workflow follows
[formatjs/formatjs](https://github.com/formatjs/formatjs/blob/main/.github/workflows/native-smoke.yml):
trusted downloader checks repository, exact commit, successful invocation, artifact
store, size and SHA256. GH jobs only download/extract/execute; they run no builds.
Both Windows compiler variants execute on each matching CPU host.

Configure hosted BuildBuddy workflows and make the organization's read-only
`BUILDBUDDY_RO_PUBLIC_KEY` secret available to this repository's GH Actions.
Automatic smoke starts from BB's `Cross-build Electron Apps` success status.
The workflow also accepts manual invocation URL + commit inputs. No tokens belong
in source or chat.

Smoke rejects mismatched host OS/CPU. It relocates the app under a path containing
spaces, verifies ASAR main/preload/renderer loading, Unicode assets, native addon,
helper execution, extra resources and stripped package scripts. Renderer sandbox
and context isolation must remain enabled. Linux/Windows check hardened startup
environment fuses; macOS verifies its ad hoc bundle with native codesign.

Linux smoke needs Xvfb, GTK3/NSS/ALSA/GBM and unprivileged user namespaces. The GH
Ubuntu job installs host test dependencies. No smoke uses `--no-sandbox` or CPU
emulation. Windows and macOS smoke require native desktop-capable runners.

## Replacing electron-builder

| Input | Rule equivalent |
| --- | --- |
| `electronDist` | Explicit runtime files or ZIP dependency |
| `directories.app`, `files` | `package_json`, `srcs` file/tree mappings |
| `asar`, `asarUnpack` | `asar`, exact `asar_unpacked` paths |
| `extraResources` | `extra_resources` outside ASAR |
| `executableName` | `executable_name` |
| `removePackageScripts` | `remove_package_scripts` |
| `electronFuses` | Supported Linux/Windows v1 settings |
| Native dependency rebuild | Target-platform C/C++ actions |

All regular files in mapped trees ship. Configure bundlers to omit source maps;
glob filtering is not implemented. Directory symlinks inside app/resource trees
are rejected; runtime ZIP symlinks are validated and retained. The sample custom
renderer protocol is separate from OS-level protocol registration.

See [parity checklist](../../docs/packaging-parity.md) for release gaps. Graph
analysis, cross-build success and native smoke success are separate evidence;
hosted results must establish the latter two for newly added variants.
