# Packaging parity

Generic migration contracts only. No private application code, settings, resource
names or infrastructure belong in this repository. This is not a claim of full
electron-builder replacement.

| Contract | Current support | Remaining work |
| --- | --- | --- |
| Target selection | Seven example OS/CPU/compiler variants; Linux x64 source desktop/package/update smoke | Source runtimes for other triples |
| Main/preload/renderer inputs | Explicit files and generated directories | Rich package-provider adapters |
| Runtime dependencies | Integrity-pinned npm v3 imports, workspace/generated providers and nested layouts; Node-API and Node/V8 addons with explicit ABI SDKs; Linux x64 source SDK | Provider-specific adapters; source SDKs for other targets |
| ASAR | Deterministic standalone/main archives, virtual links and linked entry points, minimatch unpack patterns, hashes and unpacked sidecars; multi-archive macOS plist/Windows PE integrity; complete standalone Linux source-runtime alias/sidecar/cache smoke | Complete source profiles for other triples |
| Extra resources/files | Declared file/tree mappings outside ASAR; Linux/macOS resource links; separate generated-tree link metadata through filtering, ASAR, plain apps, extra resources/files; native generated ASAR/plain-app/resource/extra-file aliases pass | Windows filesystem links |
| File selection | Declared file/tree mappings; ordered minimatch filters; root tree mounts; explicit/tracked empty directories, including prepackaged imports | — |
| Manifest metadata | Deep-merge overlays, source/generated dependency-manifest version rewrites, top-level field/script removal; shared app/update identity | Provider-specific metadata adapters |
| Runtime locales | ZIP and declared-file locale selection; Linux/Windows `.pak`, macOS main/Electron framework `.lproj`, normalized bare/regional matching; all four native hosts pass | — |
| Fuses | Named v1 settings, including macOS framework mutation before ad hoc signing | Universal macOS binaries; availability depends on runtime wire |
| Linux app | Relocatable directory, DEB desktop/MIME/protocol/icon metadata, explicit dependencies/hooks, opt-in root-owned setuid sandbox helper verified on Linux x64 | Distribution-specific confinement |
| macOS app | Branded bundle/helper metadata and ICNS icons, declared main Info.plist extensions, framework links, scoped main/inherited entitlements, hardened runtime, ad hoc signing, deterministic ZIP; explicit Developer ID signing and notarization/stapling release clients | Live Developer ID/TSA/Apple interoperability, native Gatekeeper acceptance, production entitlement policy |
| Windows app | Renamed executable, current-process Node-API/Node/V8 exports and source-built delay loading; four compiler/CPU variants; PE branding/icons/ASAR integrity; explicit Authenticode release command | Production signing trust and release identity validation |
| App version/build number | Public SemVer manifest override/validation; explicit build number/version; macOS app/helper, Windows PE/NSIS and DEB iteration | — |
| OS registration | Linux desktop/MIME declarations and declared file-type PNG/SVG icons (native PNG install/update/purge checks pass); macOS URL/document types, document icons and native LaunchServices delivery; user/machine Windows URI schemes, Open With/Default Apps file handlers, document ICO paths, extra file verbs and shortcut AppUserModelID (native x64/ARM64 MSVC installer lifecycle passes) | Richer document metadata |
| Installers | Linux DEB for amd64/arm64; native RPM v4 writer and native Fedora install/update/remove checks; source-built AppImages and embedded updater feeds for both Linux CPUs; user/machine Windows NSIS with declared tools, explicit multilingual license selection/acceptance, independent installer/uninstaller icons and owned-file uninstall; native MSIX writer with signed bootstrap Electron install/upgrade/remove on both Windows CPUs; source-built HFS+ UDIF macOS disk images with declared Finder layout/backgrounds, multilingual TEXT/RTF GUI consent and declared text companions for CLI consent, native alias and rendered-pixel checks | Live DMG Developer ID/TSA/Apple trust; production MSIX signing/OS integration and other packaging |
| Prepackaged release stages | Public immutable app import for archives/installers; layout, CPU, packaged manifest and macOS identity validation; seven cross-build variants and four native hosts pass | Release signing APIs and signature trust policy |
| Distribution archives | Public ZIP/tar/tar.gz/tar.xz/tar.bz2/tar.lz/tar.7z/7z rule, declared compressors, executable modes and relative symlinks; native macOS ZIP and Linux x64 tar.gz/tar.lz/tar.7z/7z launch | — |
| Windows portable executables | Declared NSIS/7zip tools, exact argument/environment forwarding, child exit status and junction-safe temporary cleanup; both compiler variants pass on native x64/ARM64 | — |
| electron-updater | Generic/GitHub/S3/Spaces client configuration and native discovery; SHA-512/size, content-defined external blockmaps, real client planning; Linux DEB/RPM/AppImage, Windows user/machine NSIS and macOS ARM64 Squirrel lifecycle smoke; over 99% per-user sample NSIS reuse on both CPUs, 99.7% AppImage reuse on Linux x64 and 99.83% Mac ZIP reuse on ARM64 | Other update targets, provider/publishing adapters and machine cache seeding across users |
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

MSIX implementation is in progress. Public `electron_msix` emits unsigned
deterministic ZIP64, compressed footprint XML, explicit publisher/CPU/version/PNG
logo metadata and 64 KiB SHA-256 block maps. The
[7aec9d1 BB suite](https://formatjs.buildbuddy.io/invocation/12d5556f-174d-4355-8b2a-e7deaeb27346)
independently decoded ZIP records and block ranges; its
[cross-build](https://formatjs.buildbuddy.io/invocation/61df5b32-7025-4dc8-ae76-edac23b58d92)
compiled the Windows verifier on BB. Matching Windows x64/ARM64
[native jobs](https://github.com/formatjs/rules_electron/actions/runs/42560665516)
passed actual `IAppxPackageReader`, manifest/CPU/version, every payload and
manifest hash, and modified second-block rejection. Public rule wiring passed the
[d15af96 suite](https://formatjs.buildbuddy.io/invocation/6c7b7ec2-2838-4c41-86c1-011e27e199a2),
[seven-variant cross-build](https://formatjs.buildbuddy.io/invocation/17147615-873f-4a49-b471-e67118b15631)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42561564137),
including both Windows Packaging API gates. Fixture remains a minimal PE app.
Signed minimal fixtures also passed native trust/tamper rejection and
install/helper launch/removal on both Windows CPUs; see [signing proof](signing.md).
The [full-app MSIX gate](msix.md) subsequently passed bootstrap Electron
install/launch/upgrade/removal on both Windows CPUs, with package identity,
sandboxed renderer, native addon/helper and integrity metadata checks. The full
source runtime and production signing remain unverified. App Installer
package/bundle metadata, publication and native update gates are tracked in
[App Installer updates](appinstaller.md). Empty directory leaves and symlinks fail
explicitly. See [MSIX](msix.md).

MSIX URI/file handler registration also passed native Shell enumeration after
install and upgrade, then removal checks on both Windows CPUs. Rich document
metadata remains open. PNG document assets and URI/file activation now have
native coverage; see [MSIX](msix.md) for evidence and fixture scope.

Generic conditional HTTP publication now has an explicit release tool and real
socket-based integration tests: verified immutable payloads/blockmaps upload
before ETag-guarded channel promotion. The [BB suite](https://formatjs.buildbuddy.io/invocation/dcd45a49-c63b-4107-a8fb-be76a3bcb6b0)
passed the public executable's socket-based publication tests. Provider
APIs and production publication remain open. See [updates](updates.md).

The [GitHub release adapter](github-publication.md) adds multi-feed snapshots,
commit-pinned tags, verified draft uploads, recovery and immutable public-release
retries. Its BB socket protocol tests passed. Native GitHub provider discovery
and live publication are tracked separately in that contract.

Windows release signing now has an explicit PE/MSIX command with private runtime
credentials, encrypted-key support, certificate SHA-256 pinning and verified
output commit. The [BB suite](https://formatjs.buildbuddy.io/invocation/ed0b04c2-3a52-426a-a65c-2261ec0456d5)
passed real local HTTPS RFC 3161 timestamps and TLS/trust/failure rejection.
Production trust, remote credential services and native acceptance of release
identities remain open. See [signing](signing.md).

The [machine NSIS gate](https://github.com/formatjs/rules_electron/actions/runs/42589695874)
passed Program Files/HKLM install, real elevated updater replacement and owned
removal on Windows x64/ARM64. Both elevation helper compiler variants passed
argument/token/exit checks and detached launch. Interactive consent and first-
update differential cache seeding across users remain open. See
[Windows installers](windows-installers.md).

The [Node/V8 addon SDK](native-addons.md) now passes actual shared backing-store
ownership and byte checks in the main thread and a worker on all four native
hosts. All seven variants cross-build with Electron's matching source-built
libc++ ABI. The Linux source SDK also passes those checks in the standalone
source runtime after relocation and renaming. The [source desktop handoff](https://github.com/formatjs/rules_electron/actions/runs/42790155958)
also passes Linux x64 desktop, packages and updater launch with that SDK. Source
runtimes/SDKs for other platforms remain open.
