# Packaging parity

Generic migration contracts only. No private application code, settings, resource
names or infrastructure belong in this repository. This is not a claim of full
electron-builder replacement.

| Contract | Current support | Remaining work |
| --- | --- | --- |
| Target selection | Seven example OS/CPU/compiler variants | Full source-built Electron runtime |
| Main/preload/renderer inputs | Explicit files and generated directories | Rich package-provider adapters |
| Runtime dependencies | Integrity-pinned npm v3 imports and bundled-owner validation; explicit workspace/generated package providers and nested layouts; target-built Node-API addon/helper | Provider-specific adapters; Electron Node/V8 ABI toolchains |
| ASAR | Deterministic standalone/main archives, virtual links and linked entry points, minimatch unpack patterns, hashes and unpacked sidecars; multi-archive macOS plist/Windows PE integrity | Direct unpacked alias operations |
| Extra resources/files | Declared file/tree mappings outside ASAR; Linux/macOS resource link declarations; BB ZIP/import/TAR/DEB boundaries and native macOS signed-link checks pass | Windows links and generated-tree link metadata |
| File selection | Declared file/tree mappings; ordered minimatch filters; root tree mounts; explicit/tracked empty directories, including prepackaged imports | — |
| Manifest metadata | Deep-merge overlays, source/generated dependency-manifest version rewrites, top-level field/script removal; shared app/update identity | Provider-specific metadata adapters |
| Runtime locales | Explicit file mappings or non-macOS ZIP locale selection | Broader runtime-provider integration |
| Fuses | Named v1 settings, including macOS framework mutation before ad hoc signing | Universal macOS binaries; availability depends on runtime wire |
| Linux app | Relocatable directory, DEB desktop/MIME/protocol/icon metadata, explicit dependencies/hooks, opt-in root-owned setuid sandbox helper verified on Linux x64 | Distribution-specific confinement |
| macOS app | Branded bundle/helper metadata and ICNS icons, declared main Info.plist extensions, framework links, scoped main/inherited entitlements, hardened runtime, ad hoc signing, deterministic ZIP | Developer ID, production entitlement policy, notarization/stapling |
| Windows app | Renamed executable, current-process Node-API exports, four compiler/CPU variants; PE version/product strings, ICO icons and ASAR integrity through declared source Node/resedit tooling | General addon delay-load/import-library tooling, Authenticode |
| App version/build number | Public SemVer manifest override/validation; explicit build number/version; macOS app/helper, Windows PE/NSIS and DEB iteration | — |
| OS registration | Linux desktop/MIME declarations and declared file-type PNG/SVG icons (native icon smoke pending); macOS URL/document types, document icons and native LaunchServices delivery; per-user Windows URI schemes, Open With/Default Apps file handlers, declared document ICO paths (native x64/ARM64 install/update checks pass) and shortcut AppUserModelID | Richer document metadata and Windows verbs |
| Installers | Linux DEB for amd64/arm64; per-user Windows NSIS with declared tools, independent installer/uninstaller icons and owned-file uninstall | RPM/AppImage, macOS disk images, Windows per-machine NSIS/MSIX and other packaging |
| Prepackaged release stages | Public immutable app import for archives/installers; layout, CPU, packaged manifest and macOS identity validation; seven cross-build variants and four native hosts pass | Release signing APIs and signature trust policy |
| Distribution archives | Public ZIP/tar/tar.gz/tar.xz/tar.bz2 rule, explicit compression, executable modes and relative symlinks; native macOS ZIP and Linux x64 tar.gz launch | 7z and other archive formats |
| electron-updater | Generic config/manifests, SHA-512/size, content-defined external blockmaps, real client discovery/planning; Linux DEB and Windows NSIS lifecycle smoke; over 99% sample NSIS reuse on both CPUs | Other installed-app update targets, embedded AppImage maps, provider/publishing adapters |
| Native smoke | Scripts/workflows for four native host types | Hosted results establish actual execution coverage |

All compilation, generators, assembly and ad hoc signing run on BB Linux
execution workers. GH smoke jobs only download and execute those outputs. Linux
ARM64 is cross-built without native smoke in the current host set. macOS ARM64
and Windows x64/ARM64 each use matching hosted runners; both Windows compiler
variants run on the corresponding CPU host. No emulation substitutes for smoke.

Keep this checklist current as each contract gains a concrete rule and meaningful
validation. Production migration requires closing the relevant release gaps.

Empty directory leaves flow through file collection, plain app assembly and
ASAR directory entries. Bazel drops untracked empty directories from tree
inputs, so producers supply `ElectronFileTreeInfo.directory_manifest`: a declared
JSON file listing normalized tree-relative directory paths. `electron_files`
propagates that manifest; ASAR/app rules consume it. App assembly emits its own
manifest for ZIP/tar.gz release archives and DEB/NSIS packaging. The
[8172dc6 assembly suite](https://formatjs.buildbuddy.io/invocation/30445f78-79fc-4636-8f8f-8dc932ad9f36)
passed separate collection, ASAR, app and release-archive action boundaries.
The [33af2a4 suite](https://formatjs.buildbuddy.io/invocation/0fb78fb8-8e3f-4537-8f2e-2b9a72bcfc0e)
also passed immutable import, real DEB directory entries and generated NSIS
install/uninstall ownership checks. Native smoke reads empty directories inside
ASAR and extra resources. The
[a5f18c1 cross-build](https://formatjs.buildbuddy.io/invocation/fc93ed89-7fe8-4247-ac3d-592fa5175313)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42517726082)
passed, including macOS signature checks and both Windows compiler variants.
See the [release plan](release-plan.md) and [updater contract](updates.md).
Linux package behavior and its native validation live in [Linux packages](linux-packages.md).
Windows installer scope and validation live in [Windows installers](windows-installers.md).
