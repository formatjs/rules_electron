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
    protocols = ["example-desktop"],
    file_associations = {".example": "Example Document"},
)
```

Output is unsigned. `identity_name` defaults to app `app_id`; publisher is an
explicit certificate subject. Signing must preserve both. App native
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
files replace them. Production signing, URI/file activation behavior,
language/scale assets and App Installer
publishing remain open. The source-built signer now passes a
[BB MSIX signing/verification round trip](https://formatjs.buildbuddy.io/invocation/feb26e4f-2453-4ff3-ab50-81f58c7dd10e),
including preserved payload hashes and reproducible signed bytes. Signed minimal
fixtures passed native trust, tamper rejection, install/helper launch/removal and
certificate cleanup on both Windows CPUs; see [signing stages](signing.md).
This rule does not establish electron-updater support for MSIX. Existing NSIS updater lifecycle stays independently covered.

The desktop example now includes signed v1/v2 MSIX packages of the real sample
app, using the explicitly labeled bootstrap Electron runtime. Both contain the
renderer, preload, npm closure, target-built addon/helper and ASAR integrity
metadata. Physical empty resource directories are omitted explicitly; virtual
ASAR directories remain. Installed smoke requires Electron's
[`process.windowsStore`](https://www.electronjs.org/docs/latest/api/process#processwindowsstore-readonly)
package identity, keeps Chromium's sandbox enabled and checks both versions
across a native MSIX upgrade/removal. It reads integrity metadata without
modifying the installed WindowsApps tree. Portable-app tamper tests remain
separate. NSIS updater discovery is not run inside MSIX.

The [5ded5f6 BB suite](https://formatjs.buildbuddy.io/invocation/46b6948e-0d57-4c5b-b64c-640d9216984e)
and [seven-variant cross-build](https://formatjs.buildbuddy.io/invocation/00631cb7-3597-494c-b303-de0dd1db95aa)
passed. Native [Windows x64](https://github.com/formatjs/rules_electron/actions/runs/42572824736/job/129014064007)
and [ARM64](https://github.com/formatjs/rules_electron/actions/runs/42572824736/job/129014064054)
installed v1, launched actual Electron, upgraded to v2, launched again and removed
the package and temporary certificate. Both versions reported MSIX identity and
native CPU, exercised the sandboxed renderer/preload, loaded the target-built
addon/helper and checked packaged resources and multi-ASAR integrity metadata.
This proves bootstrap-runtime deployment; the full source-built runtime remains
unverified.

`protocols` and `file_associations` declare packaged desktop handlers using
Microsoft's [protocol](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-uap3-protocol)
and [file association](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-uap3-filetypeassociation)
schemas. Windows passes the URI or file path as one quoted argument; app code
owns argument handling. File-handler identities stay stable across package
versions. Package deployment advertises candidates without setting user defaults.
The native gate enumerates protocol/file handlers through public Shell APIs,
matches the package AppUserModelID after install and upgrade, then requires its
handlers absent after removal. The
[a414167 suite](https://formatjs.buildbuddy.io/invocation/e7a825cf-7484-4ddd-89c0-53e6e537dad7)
and [cross-build](https://formatjs.buildbuddy.io/invocation/9e8e3e21-1436-4f16-be19-7b2fa0265ad7)
passed. Native [Windows x64](https://github.com/formatjs/rules_electron/actions/runs/42574732274/job/129019965855)
and [ARM64](https://github.com/formatjs/rules_electron/actions/runs/42574732274/job/129019965955)
passed both schemes and file types after install/upgrade, then absence after
removal, plus the real Electron lifecycle. The earlier ARM64 run passed these MSIX
checks before an unrelated NSIS update timeout; see [installer diagnostics](windows-installers.md).

Cold activation checks now invoke the installed app through its registered
[`IAssocHandler`](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-iassochandler-invoke),
using both protocol schemes and file extensions after install and upgrade.
Electron must report the exact URI or file path, Unicode document content,
package identity, CPU and version, then exit. Reports require a pre-created
nonce directory in the user's temporary directory. The activation helper is
compiled on BB; native hosts only execute it. The [da21d47 matrix](https://github.com/formatjs/rules_electron/actions/runs/42715968227)
delivered all four handlers after install and upgrade on Windows x64 and ARM64,
then removed handlers, package and fixture certificate. The x64 job later failed
its separate machine NSIS process-observer gate. The fixture now reports its
canonical executable path before exit; that adjustment awaits validation.

`electron_msix.file_association_icons` maps declared PNG labels to registered
extensions, for example `{"//assets:document.png": ".example"}`. Each mapping
requires one PNG file and a distinct registered extension. The package adds a
stable asset path and a `uap:Logo` declaration; the source file need not already
be inside the app. PNG validation, asset collision checks and block hashes apply
to these inputs too. Native smoke checks the deployed manifest and exact image
bytes after install and upgrade; those checks passed on both Windows CPUs in
the same matrix. Explorer visual rendering remains outside these checks. See
[`uap:Logo`](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-uap-logo).
