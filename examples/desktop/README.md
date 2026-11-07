# Desktop packaging migration example

Independent consumer workspace. Generic app, written from scratch: main/preload,
renderer directory output, Node-API addon, native helper and extra resources.
No private application code or configuration belongs here.

**Temporary bootstrap:** this example explicitly downloads official Electron
39.0.0 Linux archives, pinned by SHA256. They are test runtimes, not source-built
Electron or a production release recommendation. The source overlay does not yet
link a complete runtime. Once available, replace `:runtime` with an
`electron_runtime` adapter over those outputs. App content and packaging rules
remain the same. The core rules never download Electron.

## Build and run

From this directory:

```sh
bazel build //:app
./bazel-bin/app/sample-desktop

# Actual renderer/preload/addon/helper smoke after relocation.
bazel test //:smoke_test --test_output=errors

# Cross-compile addon and helper; assemble the ARM64 runtime without executing it.
bazel build --platforms=@rules_electron//platforms:linux_aarch64 //:app
```

Linux x86_64 smoke requires Xvfb, GTK3/NSS/ALSA/GBM libraries and unprivileged user
namespaces. On Ubuntu 22.04, install `xvfb libgtk-3-0 libnss3 libasound2 libgbm1`.
Test creates its own display with no TCP listener; no xauth or existing desktop
session required. It never passes `--no-sandbox`. The example excludes the setuid
sandbox helper and uses Chromium's user-namespace sandbox. Unsupported host
sandbox settings fail the smoke rather than reducing isolation.

Output layout:

```text
app/
  sample-desktop
  ...Electron runtime libraries, data, notices, en-US locale...
  resources/
    app.asar
    app.asar.unpacked/node_modules/example-native/addon.node
    native/helper
    config/settings.json
```

The renderer uses a secure custom protocol with a fixed resource allowlist.
Preload exposes a small IPC bridge; renderer Node integration stays disabled.
The addon builds from C using stable Node-API headers and LLVM, without node-gyp.
Other addons using Node/V8 internals need matching Electron headers and ABI flags.
The bundled `example-native` package is local example code, not an npm download.

## Replacing electron-builder

| electron-builder input | Native Bazel equivalent here |
| --- | --- |
| `electronDist` | Explicit target-platform `electron_runtime` dependency |
| `directories.app`, `files` | `package_json`, explicit `srcs` mappings |
| Bundled main/preload/renderer | Existing Bazel outputs; renderer demonstrates a tree artifact |
| `asar` | `asar = True`, deterministic header/content and SHA256 block hashes |
| `asarUnpack` | `asar_unpacked`, exact declared app-relative files |
| `extraResources` | `extra_resources`, outside ASAR with preserved executable modes |
| `executableName` | `executable_name` |
| `removePackageScripts` | `remove_package_scripts = True` |
| `electronFuses` | Explicit supported Linux v1 `fuses` settings |
| Native dependency rebuild | Separate target-platform Bazel C/C++ actions |
| `--dir` | Relocatable directory artifact |

Source maps are omitted by the declared input list. For bundler tree artifacts,
configure the bundler to exclude maps before packaging; every regular file in
the tree is shipped. Directory symlinks and overlapping destinations fail; regular
file symlink leaves from Bazel input projection are copied as regular files. No
package-manager discovery, dependency installation or lifecycle scripts run.

Smoke checks the packaged app under a path containing spaces, after copying away
from Bazel outputs. It loads ASAR main/preload/renderer content, reads Unicode
assets, loads the unpacked native addon, executes the helper and reads extra
resources. It verifies package scripts were removed, renderer sandbox/context
isolation are enabled and Node startup environment overrides are ignored.

## Remaining release work

This establishes Linux unpacked-app behavior. Source-built runtime integration,
OS-level protocol registration, desktop metadata/icons, installers, update feeds,
macOS frameworks/helper apps, signing/notarization and Windows resources remain.
No production migration or cross-platform release parity is claimed.

BuildBuddy builds both Linux architectures and runs the real x86_64 smoke on its
workflow host; assembly and compilation use remote execution. Root fixture
cross-link checks still cover five platforms. Hosted workflow results are separate
from local validation.
