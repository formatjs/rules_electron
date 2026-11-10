# Windows portable executables

`electron_portable` packages a Windows `electron_app` with the same declared
execution NSIS/7zip tools used by `electron_nsis`. Assembly and compilation run
on BB Linux. The launcher requests user execution and checks the native payload
architecture before extracting.

```starlark
load("@rules_electron//electron:portable.bzl", "electron_portable")

electron_portable(
    name = "portable",
    app = ":app",
    tool = ":nsis_tool",
    verify_reproducible = True,
)
```

Each launch gets a unique temporary app directory. Arguments come from the raw
Windows command line, including `/D=` arguments that NSIS otherwise consumes.
Command lines exceeding the declared compiler's string capacity fail before
extraction. The launcher waits for the app, preserves its exit status and retries
owned extraction cleanup for up to 30 seconds. It creates no installation
registry entries, uninstaller or shortcuts. Cleanup removes directory junctions
without traversing their targets. Extraction lives outside NSIS's plugin tree,
so NSIS's automatic recursive cleanup never owns app-created files. Symlinks and unsafe/colliding
Windows names fail during packaging; tracked empty directories are preserved.

The child receives the [electron-builder portable variables](https://www.electron.build/docs/nsis/#portable):
`PORTABLE_EXECUTABLE_DIR`, `PORTABLE_EXECUTABLE_FILE` and
`PORTABLE_EXECUTABLE_APP_FILENAME`. The first two follow the launcher's current
location/name. `app_filename` overrides the third; its default is the payload
executable stem. `icon` accepts a declared ICO. Standard NSIS compression options
and the portable `script` output group are available. Reproducibility checks
relocate app/icon inputs and compare both executable and script bytes.

Portable executables are not NSIS updater installers. Direct portable targets
are rejected by `electron_update_feed`; installed NSIS update contracts remain
separate. Publishing/signing a portable file uses the ordinary final-artifact
release interfaces.

The [3e1f348 BB suite](https://formatjs.buildbuddy.io/invocation/685bd6b7-b347-4b25-b69b-f42e2ce0bd9f)
and [cross-build](https://formatjs.buildbuddy.io/invocation/c9f774ab-83e1-4ba4-b34f-e3e7aa552002)
passed. [All four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42762400895)
passed, testing those artifacts. Windows x64/ARM64 each launched both compiler
variants from renamed Unicode paths, exercising real renderer/native addons,
exact argument/environment forwarding, exit status 42 and concurrent extraction.
Cleanup removed owned files and roots while preserving an external junction
target. Application registrations and parent environment stayed unchanged.
