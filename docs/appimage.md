# AppImage

`electron_appimage` assembles a declared AppDir, source-built static type-2 runtime
and deterministic SquashFS filesystem. Linux x64 and ARM64 targets use the same
Linux BB execution platform; packaging never executes target binaries.

```starlark
load("@rules_electron//electron:appimage.bzl", "electron_appimage")
load("@rules_electron//electron:update.bzl", "electron_update_feed")

electron_appimage(
    name = "desktop_appimage",
    app = ":desktop",
    icon = "icon.svg",
    protocols = ["example"],
    file_associations = ["application/x-example"],
)

electron_update_feed(
    name = "appimage_feed",
    artifacts = {":desktop_appimage": "desktop.AppImage"},
    embedded_blockmaps = ["desktop.AppImage"],
    package_json = ":release_package.json",
    platform = "linux",
    architecture = "x64",
    release_date = "2026-01-01T00:00:00Z",
)
```

The rule accepts a PNG/SVG icon, desktop description/categories, URI schemes and
MIME types. Its native AppRun launcher reads the declared executable basename,
passes application arguments and honors electron-updater's
`APPIMAGE_EXIT_AFTER_INSTALL=true` before starting the app. AppRun,
`.electron-executable`, `.DirIcon` and generated desktop/icon paths are reserved.
Declared resource links and tracked empty directories survive assembly.

Compression is explicit: `gzip` or `zstd`, default level 9. Ownership, timestamps,
permissions, thread count, memory budget, locale and tool environment are fixed.
The runtime, launcher and application executable must match target ELF CPU.
Runtime validation rejects shared-library imports and an ELF interpreter.

Embedded updater maps are enabled by default. Maps cover runtime + filesystem,
use content-defined chunks and SHA-256 checksums, then raw deflate and a four-byte
big-endian compressed-size trailer. Feed generation validates map coverage and
emits `blockMapSize` alongside final SHA-512/size. This matches the pinned
6.8.11 client reader contract. External maps remain separate gzip files.

All tools build from pinned sources with native Bazel C/C++ rules:

- SquashFS 4.7.5, zlib and zstd.
- Type-2 runtime `fedfad51acc2860b2916a1eef32ba4a500ff31ef`.
- libfuse 3.15.0, Squashfuse 0.5.2 and native BCR mimalloc 3.5.3.

Runtime/launcher alone select LLVM's musl platform and PIC settings. Target
configuration is checked in. A declared Python action generates Squashfuse swap
includes; no host `sed`, configure, Meson, Make, CMake or foreign-cc action runs.
The libfuse mount patch comes from the pinned runtime source. A linker-script
patch places metadata before `.text`, since static PIE has no `.interp`.

Runtime foundation passed [BB tests](https://formatjs.buildbuddy.io/invocation/9f538ebc-efad-4e04-84f4-0e4d45eee3a9)
and [cross-builds](https://formatjs.buildbuddy.io/invocation/990be492-1b3b-4026-9073-101ec8bc3d66)
at `2534183`. The native Linux x64 test executed real gzip/zstd payloads through
extraction and extract-and-run. ARM64 was linked without execution.

The public packaging rule, launcher, embedded maps and feed additions are pending
BB validation. The updated gate checks changed paths/mtimes, metadata, resource
links, empty directories, chunk checksums and exit-after-install behavior.
FUSE-mounted launch and an installed Electron app's real electron-updater
replacement/differential-download lifecycle remain open. No emulation substitutes
for native smoke.
