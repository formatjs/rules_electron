# Packaging parity

Generic migration contracts only. No private application code, settings, resource
names or infrastructure belong in this repository. This is not a claim of full
electron-builder replacement.

| Contract | Current support | Remaining work |
| --- | --- | --- |
| Target selection | Seven example OS/CPU/compiler variants | Full source-built Electron runtime |
| Main/preload/renderer inputs | Explicit files and generated directories | Rich package-provider adapters |
| Runtime dependencies | Explicit Node-API package, target-built helper/addon | General npm closure handling; Electron Node/V8 ABI toolchains |
| ASAR | Deterministic header, hashes, unpacked native files; macOS plist and Windows PE header integrity | Additional ASAR files; native coverage tracked separately |
| Extra resources | File/tree mappings, normalized modes | Arbitrary resource-tree directory symlinks |
| File selection | Explicit whitelist; generated tree contents retained | Include/exclude glob rules and map filtering |
| Manifest scripts | Root package scripts removable | General dependency manifest rewriting |
| Runtime locales | Explicit file mappings or non-macOS ZIP locale selection | Broader runtime-provider integration |
| Fuses | Named v1 settings, including macOS framework mutation before ad hoc signing | Universal macOS binaries; availability depends on runtime wire |
| Linux app | Relocatable directory, DEB desktop/MIME/protocol/icon metadata, explicit package dependencies and hooks | Setuid sandbox installation, distribution-specific confinement |
| macOS app | Branded bundle/helper metadata, framework links, ad hoc signing, deterministic ZIP | Icons, Developer ID, entitlements policy, notarization/stapling |
| Windows app | Renamed executable, current-process Node-API exports, four compiler/CPU variants; PE version/product strings and ASAR integrity through declared source Node/resedit tooling | General addon delay-load/import-library tooling, PE icons, Authenticode |
| App version/build number | Public SemVer manifest override/validation; explicit build number/version; macOS app/helper, Windows PE/NSIS and DEB iteration | — |
| OS protocol registration | Linux desktop/MIME declarations; per-user Windows NSIS URI schemes | macOS registration; Windows file associations and shortcut AppUserModelID |
| Installers | Linux DEB for amd64/arm64; per-user Windows NSIS with declared tools and owned-file uninstall | RPM/AppImage, macOS disk images, Windows per-machine NSIS/MSIX and other packaging |
| Prepackaged release stages | Internal ad hoc Mac signing stage only | Public sign/package-prepackaged APIs and verification policy |
| Distribution archives | Public ZIP/tar.gz rule, explicit compression, executable modes and relative symlinks; native macOS release ZIP smoke | Additional archive formats; native tar.gz release smoke |
| electron-updater | Generic config/manifests, SHA-512/size, content-defined external blockmaps, real client discovery/planning; Linux DEB and Windows NSIS lifecycle smoke; over 99% sample NSIS reuse on both CPUs | Other installed-app update targets, embedded AppImage maps, provider/publishing adapters |
| Native smoke | Scripts/workflows for four native host types | Hosted results establish actual execution coverage |

All compilation, generators, assembly and ad hoc signing run on BB Linux
execution workers. GH smoke jobs only download and execute those outputs. Linux
ARM64 is cross-built without native smoke in the current host set. macOS ARM64
and Windows x64/ARM64 each use matching hosted runners; both Windows compiler
variants run on the corresponding CPU host. No emulation substitutes for smoke.

Keep this checklist current as each contract gains a concrete rule and meaningful
validation. Production migration requires closing the relevant release gaps.
See the [release plan](release-plan.md) and [updater contract](updates.md).
Linux package behavior and its native validation live in [Linux packages](linux-packages.md).
Windows installer scope and validation live in [Windows installers](windows-installers.md).
