# rules_electron

Native Bazel rules for Electron app assembly. Linux unpacked apps first.

Current implementation assembles declared runtime files and app files into a
relocatable directory, with optional ASAR, unpacked native modules, extra resources
and Linux fuse settings. No electron-builder, package installation, network access,
GN or Ninja runs inside assembly actions. Python runs through a pinned Bazel
execution toolchain; the target runtime is never executed during assembly.

**Source runtime pending:** [formatjs/electron](https://github.com/formatjs/electron)
builds source components but does not yet link a complete Electron executable.
The [desktop example](examples/desktop/README.md) exercises real app behavior with
an explicitly labeled, pinned official bootstrap runtime. No source-built Electron
app launch is claimed. The Electron source module has not been published to BCR.

## Usage

Given a source-built Linux Electron executable and its complete runtime files:

```starlark
load("@rules_electron//electron:defs.bzl", "electron_app", "electron_runtime")

electron_runtime(
    name = "runtime",
    binary = ":source_built_electron",
    files = {
        ":icu_data": "icudtl.dat",
        ":english_locale": "locales/en-US.pak",
        # Declare every runtime dependency from the source build.
    },
)

electron_app(
    name = "app",
    runtime = ":runtime",
    package_json = "package.json",
    srcs = {
        "main.js": "main.js",
        "renderer/index.html": "renderer/index.html",
    },
)
```

Runtime mappings use single-file labels as keys. App `srcs` and `extra_resources`
also accept a single tree artifact per label, mapped beneath the destination path.
Paths must be normalized and relative. `package.json`'s `main` must name a declared
file exactly; missing `main` defaults to `index.js`. Bundle TypeScript/renderer
code with existing Bazel rules before assembly. Declare npm runtime files
explicitly; assembly does not resolve dependencies or rebuild native addons.

Output: `bazel-bin/<package>/app/`, executable `app/electron`, app content under
`app/resources/app/`. Set `executable_name` to rename the binary. Runtime adapters
must exclude `resources/app`, `resources/app.asar` and `resources/app.asar.unpacked`.
Modes normalize to 0755 for executables, 0644 otherwise; timestamps to epoch.
Setuid sandbox installation is outside this directory format.

Set `asar = True` for deterministic `resources/app.asar`; `asar_unpacked` lists
exact app-relative files stored alongside it. `extra_resources` maps files or
trees beneath `resources/`, outside the app archive. Set `remove_package_scripts`
to drop development scripts from the packaged manifest. No implicit file filtering
or native-addon rebuilds occur.

Linux v1 `fuses` accepts `"on"`/`"off"` for `runAsNode`,
`enableNodeOptionsEnvironmentVariable`, `enableNodeCliInspectArguments`,
`onlyLoadAppFromAsar` and `grantFileProtocolExtraPrivileges`. Unspecified fuses
remain unchanged; missing/removed fuses fail. `onlyLoadAppFromAsar = "on"` requires
ASAR. This does not embed platform ASAR-integrity metadata or sign binaries.
Installers, OS branding and signing remain pending.

## Development

```sh
bazel test //...
bazel build --platforms=//platforms:linux_aarch64 //tests:app
bazel run @buildifier_prebuilt//:buildifier -- -mode=check -r .
```

`buildbuddy.yaml` follows
[rules_formatjs CI](https://github.com/formatjs/rules_formatjs/blob/main/buildbuddy.yaml):
Linux tests on BuildBuddy remote execution, native fixture cross-linking for Linux
x86_64/arm64, macOS x86_64/arm64 and Windows x86_64 (MinGW fixture). Linux assembly additionally
cross-builds for both architectures. Cross-linking does not prove native execution
or Electron support for those platforms. Runtime/build tools remain in target/exec
configurations respectively. Configure BuildBuddy credentials through CI settings
or `.bazelrc.user`; credentials do not belong in source.

The independent desktop workspace also cross-builds its real app/addon/helper for
both Linux architectures. A separate BuildBuddy action installs GUI test host
dependencies, then runs its sandboxed x86_64 relocation smoke locally on the
workflow host. Build actions still use remote execution.

See [design](docs/architecture.md) for source integration and next milestones.
