# rules_electron

Native Bazel rules for Electron app assembly. Linux unpacked apps first.

Current implementation assembles declared runtime files and app files into a
relocatable directory. No electron-builder, package installation, network access,
GN or Ninja runs inside assembly actions. Python runs through a pinned Bazel
execution toolchain; the target runtime is never executed during assembly.

**Source runtime pending:** [formatjs/electron](https://github.com/formatjs/electron)
builds source components but does not yet link a complete Electron executable.
This repo's native fixture tests packaging only. No source-built Electron app
launch is claimed. The Electron source module has not been published to BCR.

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

Mappings use single-file labels as keys and normalized destination paths as
values. Generated files work too. `package.json`'s `main` must name a declared
file exactly; missing `main` defaults to `index.js`. Bundle TypeScript/renderer
code with existing Bazel rules before assembly. Declare npm runtime files
explicitly; assembly does not resolve dependencies or rebuild native addons.

Output: `bazel-bin/<package>/app/`, executable `app/electron`, app content under
`app/resources/app/`. Runtime adapters must exclude `resources/app` and
`resources/app.asar`. Linux only; no ASAR, installers, branding, fuses or signing
yet. Modes normalize to 0755 for executables, 0644 otherwise; timestamps to epoch.
Setuid sandbox installation is outside this initial directory format.

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

See [design](docs/architecture.md) for source integration and next milestones.
