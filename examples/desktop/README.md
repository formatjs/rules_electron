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

GitHub Actions drives BB remote builds from the example workspace:

```sh
bazel build --config=bb-workflow --config=msvc-license --lockfile_mode=error //:cross_build_smoke_bundle
```

MSVC configuration acknowledges the Visual Studio runtime license and must only
run on licensed hosts. Target transitions select static CRT and disable the
default dynamic CRT feature for MSVC variants. Before emitting any smoke archive,
the BB action checks runtime, addon and helper architectures for all seven apps,
including Linux ARM64 without a native host.

Official Electron 39.0.0 distributions are SHA-256-pinned runtime inputs. The
example packages those prebuilts; it does not build Electron, Chromium or
Electron's embedded Node. Runtime downloads happen during repository fetching;
assembly actions receive declared files and never access the network.
Core rules do not download Electron themselves.

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
small stable-ABI example. A second context-aware Node/V8 addon uses the explicit
Electron SDK through `electron_cc_addon`; its worker execution and wrong-ABI
rejection checks are pending hosted validation. Windows Node/V8 addons use MSVC
ABI even in GNU LLVM app variants. See [native addons](../../docs/native-addons.md).

## Native smoke handoff

BB publishes `electron-smoke-{linux-x64,macos-arm64,windows-x64,windows-arm64}.zip`.
Each native job downloads only its host's archive. Both Windows compiler variants
and that CPU's installers share one archive. Linux ARM64 apps/packages remain
declared cross-build inputs but are omitted from native transport.
GitHub Actions relays BB-built archives as immutable artifacts from the same
workflow run. Native jobs download, extract and execute their host's archive;
they run no builds. Both Windows compiler variants execute on each matching CPU.
See [CI setup](../../tools/ci/README.md) for organization keys and native runners.

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
