# Packaging parity

Generic migration contracts only. No private application code, settings, resource
names or infrastructure belong in this repository. This is not a claim of full
electron-builder replacement.

| Contract | Current support | Remaining work |
| --- | --- | --- |
| Target selection | Seven example OS/CPU/compiler variants | Full source-built Electron runtime |
| Main/preload/renderer inputs | Explicit files and generated directories | Rich package-provider adapters |
| Runtime dependencies | Explicit Node-API package, target-built helper/addon | General npm closure handling; Electron Node/V8 ABI toolchains |
| ASAR | Deterministic header, hashes, unpacked native files | Platform embedded integrity metadata |
| Extra resources | File/tree mappings, normalized modes | Arbitrary resource-tree directory symlinks |
| File selection | Explicit whitelist; generated tree contents retained | Include/exclude glob rules and map filtering |
| Manifest scripts | Root package scripts removable | General dependency manifest rewriting |
| Runtime locales | Explicit file mappings or non-macOS ZIP locale selection | Broader runtime-provider integration |
| Fuses | Supported Linux/Windows v1 settings | Signed macOS fuse mutation; additional fuse settings |
| Linux app | Relocatable unpacked directory | Desktop metadata/icons, package dependencies, sandbox installation |
| macOS app | Branded bundle/helper metadata, framework links, ad hoc signing, deterministic ZIP | Icons, Developer ID, entitlements policy, notarization/stapling |
| Windows app | Renamed executable, current-process Node-API exports, four compiler/CPU variants | General addon delay-load/import-library tooling, PE version/icon resources, Authenticode |
| App version/build number | Package version; macOS bundle version | Override/validation API and separate build number |
| OS protocol registration | None; sample custom scheme is internal renderer transport | OS registration metadata |
| Installers | None | Linux packages/hooks, macOS disk images, Windows APPX/MSIX and host-specific packaging |
| Prepackaged release stages | Internal ad hoc Mac signing stage only | Public sign/package-prepackaged APIs and verification policy |
| Distribution archives | Mac app ZIP and aggregate smoke ZIP | General release archive API and compression controls |
| electron-updater | Generic feed config, channel manifests, final-artifact SHA-512/size, external v2 blockmaps; example client discovery/planning smoke | Installable update targets, installed-app upgrades, embedded AppImage maps, provider/publishing adapters |
| Native smoke | Scripts/workflows for four native host types | Hosted results establish actual execution coverage |

All compilation, generators, assembly and ad hoc signing run on BB Linux
execution workers. GH smoke jobs only download and execute those outputs. Linux
ARM64 is cross-built without native smoke in the current host set. macOS ARM64
and Windows x64/ARM64 each use matching hosted runners; both Windows compiler
variants run on the corresponding CPU host. No emulation substitutes for smoke.

Keep this checklist current as each contract gains a concrete rule and meaningful
validation. Production migration requires closing the relevant release gaps.
See the [release plan](release-plan.md) and [updater contract](updates.md).
