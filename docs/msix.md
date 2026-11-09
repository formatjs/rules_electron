# MSIX

`electron_msix` packages an assembled Windows `ElectronAppInfo` on Linux BB
workers. No Windows executable, SDK packager or build-system wrapper runs during
assembly. Python runtime, app tree, package manifest, optional directory manifest
and three PNG logos are declared action inputs.

```starlark
load("@rules_electron//electron:msix.bzl", "electron_msix")

electron_msix(
    name = "package",
    app = ":app",
    publisher = "CN=Example",
    publisher_display_name = "Example",
    logo_44 = "assets/logo-44.png",
    logo_150 = "assets/logo-150.png",
    store_logo = "assets/store-logo-50.png",
)
```

Output is unsigned. `identity_name` defaults to app `app_id`; publisher is an
explicit certificate subject. Future signing must preserve both. App native
`build_version`/`build_number` supplies four numeric version components, padded
with zeroes. Prerelease SemVer requires an explicit numeric build version or
build number. Payload PE must match target x64/ARM64. Logos require exact 44x44,
150x150 and 50x50 dimensions.

Writer streams files through bounded temporary storage, emits ZIP64 records,
URI-encoded ZIP names, compressed footprint XML and SHA-256 hashes over each
uncompressed 64 KiB block. DEFLATE resets its dictionary after each block; final
stream terminator is outside block lengths. File order, timestamps and XML are
fixed. No host MIME database, archiver, environment identity or CPU probe enters
output.

Block format and compression follow Microsoft's
[block map schema](https://learn.microsoft.com/en-us/uwp/schemas/blockmapschema/app-package-block-map)
and [SDK writer](https://github.com/microsoft/msix-packaging/tree/master/src/msix/pack).
BB unit tests independently read ZIP records, decompress each block and verify
hashes, local-header lengths, Unicode, empty files and reproducibility. Native
Windows probes use `IAppxPackageReader` and `ValidateFileHash`, including rejection
of a modified second block. Native fixture contains a target-built PE, not a
complete Electron installation.

Current limits: empty directory leaves and symlinks fail explicitly; no placeholder
files replace them. Production signing, actual Electron install/launch,
update/remove, file/protocol registration, language/scale assets and App Installer
publishing remain open. The source-built signer now passes a
[BB MSIX signing/verification round trip](https://formatjs.buildbuddy.io/invocation/feb26e4f-2453-4ff3-ab50-81f58c7dd10e),
including preserved payload hashes and reproducible signed bytes. Signed minimal
fixtures passed native trust, tamper rejection, install/helper launch/removal and
certificate cleanup on both Windows CPUs; see [signing stages](signing.md).
This rule does not establish electron-updater support for MSIX. Existing NSIS updater lifecycle stays independently covered.
