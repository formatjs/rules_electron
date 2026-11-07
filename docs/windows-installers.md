# Windows installers

`electron_nsis` builds a per-user installer and uninstaller from a Windows
`electron_app`. The compiler runs on the execution platform; payload binaries
never execute during packaging.

```starlark
load("@rules_electron//electron:nsis.bzl", "electron_nsis", "electron_nsis_tool")

electron_nsis_tool(
    name = "nsis_tool",
    compiler = ":execution_makensis",
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

Default compression is solid zlib. `compression` also accepts `bzip2`, `lzma`
and `off`; LZMA uses an 8 MiB dictionary. `verify_reproducible = True` compiles a
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

Current scope: per-user installation, Start Menu shortcut, optional desktop
shortcut and URI schemes. Per-machine installation/elevation policy, file
associations, AppUserModelID shortcut properties, custom installer icons/UI and
release Authenticode remain pending. Paths must be valid Windows names; NSIS
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
reused only 64 KiB of roughly 125 MB installers. Content-defined maps and a
stronger native reuse threshold address that measured gap; their hosted result
must establish the performance effect.
