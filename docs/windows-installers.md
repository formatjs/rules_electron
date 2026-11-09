# Windows installers

`installer_icon` and `uninstaller_icon` accept declared ICO labels, including
generated icons. NSIS embeds them independently using its
[`Icon` and `UninstallIcon` attributes](https://nsis.sourceforge.io/Docs/Chapter4.html#instattribs).
Unspecified icons retain NSIS defaults. Invalid ICO containers fail before
compilation. App executable branding remains `electron_app.windows_icon`.

The native fixture uses different app, installer and uninstaller colors, then
extracts their executable icons through Win32. Installer reproducibility and
installed update checks also include these icons.
[BB tests](https://formatjs.buildbuddy.io/invocation/9cad5908-69d2-44eb-ac2a-18677024f240),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/b2ff0731-306d-4ddd-8d83-76eb2820bbf0)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42468846229)
passed, including distinct installer/uninstaller icons on both Windows CPUs/compiler variants.

Shortcuts receive `app_user_model_id`, defaulting to `electron_app.app_id`.
The value allows at most 128 UTF-16 units and no whitespace. Both Start Menu
and optional desktop shortcuts receive it on each installation or upgrade.
The declared NSIS data tree must include the Unicode WinShell plugin; the
example's integrity-pinned bundle already provides it.

Set the same ID early in the Electron main process:

```javascript
if (process.platform === 'win32') app.setAppUserModelId('org.example.sample-desktop');
```

See [Electron's runtime API](https://www.electronjs.org/docs/latest/api/app#appsetappusermodelidid-windows)
and [Windows shortcut identity](https://learn.microsoft.com/en-us/windows/win32/shell/enable-desktop-toast-with-appusermodelid).
Packaging sets shortcut properties; app code owns process identity. Native
smoke reads shortcut properties through Electron and process identity through
Win32, before and after installed updates.
[BB tests](https://formatjs.buildbuddy.io/invocation/e8acc136-a9d1-49a9-996d-ba494c7c053e),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/0340753a-d869-4cce-b70a-961dc7bdd773)
and [all native hosts](https://github.com/formatjs/rules_electron/actions/runs/42468452137)
passed; both Windows compiler/CPU variants checked shortcut and process identity.

`electron_nsis` builds a per-user installer and uninstaller from a Windows
`electron_app`. The compiler runs on the execution platform; payload binaries
never execute during packaging.

```starlark
load("@rules_electron//electron:nsis.bzl", "electron_nsis", "electron_nsis_tool")

electron_nsis_tool(
    name = "nsis_tool",
    compiler = ":execution_makensis",
    archive_compiler = ":execution_7zip",
    data = ":declared_nsisdir",
)

electron_nsis(
    name = "setup",
    app = ":app",
    tool = ":nsis_tool",
    protocols = ["example-desktop"],
    updater_cache_name = "example-desktop-updater",
)
```

The data tree contains NSIS `Include`, `Stubs`, `Plugins` and `Contrib` directories.
The example pins NSIS 3.13 from the public tool bundle by SHA-256. It invokes the
Linux x64 compiler directly with an explicit `NSISDIR` and `-NOCONFIG`; no wrapper,
host installation, package manager, Wine or electron-builder runs in build
actions. Compiler, stubs and plugins are bootstrap tools, not source builds in
this repository. A source-built compiler can use the same tool provider.

Default `7z` compression uses independent per-file LZMA2 streams, a 1 MiB
dictionary, two fixed encoder threads and no stored timestamps. NSIS stores the
archive without recompressing it and extracts through the declared plugin.
Automatic architecture filters are disabled: the extractor predates newer ARM64
filters. Only plain LZMA2/Copy streams are accepted; extracted file sizes are
checked before success.
`compression` also accepts solid `zlib`, `bzip2`, `lzma` and `off`; the direct
NSIS LZMA mode uses an 8 MiB dictionary. `verify_reproducible = True` compiles a
second installer using a copied input tree with changed mtimes and different
source/output paths, then requires byte equality. The example enables this on
v1 installers for both CPUs. No clock value enters generated scripts; file date
saving is disabled. Inspect generated source with output group `script`.

Installation uses HKCU, current-user shortcuts and a default directory below
Local AppData `Programs`. A custom `/D` directory remains registered for updates.
The installer checks payload PE architecture and native Windows CPU separately.
NSIS's bootstrap stub is x86, including for ARM64 payloads. Windows ARM64 runs
that stub through OS compatibility; the installed app/helper/addon are native
ARM64 and tested on a native ARM64 host.

Installers refuse nonempty unowned directories, foreign ownership markers and
foreign URI scheme registrations. Upgrades wait for app processes to exit before
running the owned old uninstaller and replacing its payload. Uninstall removes
the compiled list of owned files and empty directories, not a recursive install
root. User-created files remain. It removes protocol keys only when their owner
and launch command still match. App data and updater caches remain after uninstall.
This format does not provide transactional rollback.

Set `updater_cache_name` to the same value as the generated `app-update.yml`.
Installation seeds the current installer as `installer.exe` for
`electron-updater` differential downloads. `--updated`, `/S`, `--force-run` and
custom install directories support the updater's installer invocation. Generate
channel manifests and external blockmaps from final installers with
`electron_update_feed`; signing must finish before those hashes are calculated.

Current scope: per-user installation, Start Menu/optional desktop shortcuts,
AppUserModelID, URI schemes, Open With/Default Apps handlers and declared icons.
Per-machine installation/elevation policy, custom UI and release Authenticode
remain pending. Paths must be valid Windows names; NSIS
preprocessor expressions (`${...}` / `$%...`) and control characters in literals
are rejected.

Native smoke uses real installers and `NsisUpdater`: refuse an unowned directory
and foreign protocol, install v1 to a path with spaces, inspect registration,
launch, reject corrupted bytes, download v2 through HTTP ranges, install/launch
v2, then uninstall while preserving a user-created file. It requires actual
differential reuse, not a full-download fallback. Hosted results establish
whether this contract passes.

Initial [x64/ARM64 lifecycle validation](https://github.com/formatjs/rules_electron/actions/runs/42349256215)
passed install, hash rejection, upgrade, v2 launch and uninstall. Fixed-size maps
reused only 64 KiB of roughly 125 MB installers. Content-defined maps alone still
downloaded roughly 97%: the solid compressed stream also changed throughout.
With independent LZMA2 payload streams and content-defined maps,
[39cda07 native validation](https://github.com/formatjs/rules_electron/actions/runs/42351884226)
passed on both CPUs. x64 downloaded 776,681 of 96,256,700 bytes; ARM64 downloaded
760,466 of 89,390,353 bytes. Each reused over 99% for this sample's version-only
change. The gate requires less than 50% over ranges, with no full-download
fallback. Application changes can produce different reuse ratios.

`file_association_icons` maps registered extensions to app-relative ICO paths:

```starlark
file_associations = {".example": "Example Document"},
file_association_icons = {".example": "resources/document.ico"},
```

Include each icon through the app's declared resource/file mappings. Installer
validation requires a normalized relative path, a regular payload file and a
valid ICO container. Unspecified associations use the app executable icon.
Payload ownership covers icon upgrade/removal. User defaults remain unchanged.
Native shell resolution through
[`ASSOCSTR_DEFAULTICON`](https://learn.microsoft.com/en-us/windows/win32/api/shlwapi/ne-shlwapi-assocstr)
and Win32 image decoding passed before/after installed updates on
[Windows x64](https://github.com/formatjs/rules_electron/actions/runs/42538722589/job/128908849414)
and [Windows ARM64](https://github.com/formatjs/rules_electron/actions/runs/42538722589/job/128908849402)
for a3f7142. Both hosts also passed uninstall ownership checks.

An [ARM64 run at a414167](https://github.com/formatjs/rules_electron/actions/runs/42574365090/job/129018851852)
downloaded the update but stayed at v1 after 120 seconds. Its failure snapshot
showed a pending installer and no remaining app/installer processes. The next
[scheduled run](https://github.com/formatjs/rules_electron/actions/runs/42574732274/job/129019965955)
passed the full lifecycle. The timeout remains unexplained. Native smoke now
subscribes to Windows process start/stop events around the real updater launch;
it records only fixed fixture names and numeric exit codes. Success requires
observed installer start and zero exit status in addition to installed v2. This
observer uses existing Windows APIs; no code is compiled on the smoke host.
Hosted validation is pending. Successful repeat validation does not close the
intermittent failure.
