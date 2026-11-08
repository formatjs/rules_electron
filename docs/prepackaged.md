# Prepackaged apps

`electron_prepackaged_app` imports an existing app tree artifact, Linux app ZIP or
macOS `.app` ZIP into `ElectronAppInfo`. Archives and DEB stream Linux ZIP inputs;
NSIS requires a Windows directory payload. Linux ZIPs may be flat or contain one
wrapping directory. Inputs remain immutable.

```starlark
load("@rules_electron//electron:prepackaged.bzl", "electron_prepackaged_app")

electron_prepackaged_app(
    name = "release_app",
    src = ":assembled_app",
    package_json = ":release_package_json",
    executable_name = "sample-desktop",
    product_name = "Sample Desktop",
    app_id = "org.example.sample-desktop",
    build_number = "7",
)
```

The target OS and CPU come from Bazel platform constraints. A validation action
checks ELF64, PE32+ or Mach-O executable type/CPU; macOS universal executables
must contain a matching slice. It reads the actual plain or ASAR-packaged
`package.json`, including linked and unpacked manifests, and compares `name`,
`version` and `main`. Missing `main` means `index.js`. macOS bundle executable,
identifier, display name, app version and native build version must match the
declared metadata. Input inventories reject escaping, cyclic and dangling links.

The original artifact is returned unchanged. Validation uses Bazel's transitive
`_validation` output group; keep validation actions enabled for release builds.
No target executable runs. No install, dependency pruning or metadata rewriting
occurs. Existing signature bytes remain intact; this rule does not establish
signature trust, notarization or the identity of every nested executable.
Developer ID and Authenticode release signing remain separate unfinished work.

The generic example routes both app versions through this import before release
packaging. [BB unit tests](https://formatjs.buildbuddy.io/invocation/4148b234-9a16-4eab-a4c8-fb61e8ac7b2f),
[seven cross-build variants](https://formatjs.buildbuddy.io/invocation/dd2f6381-0380-466e-9571-59c92855ba53)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42472770974)
passed at `bfeedd6`. Native smoke covers renderer/IPC/addons, macOS signature
checks and installed DEB/NSIS update lifecycles; Windows exercises both MSVC
and GNULLVM variants on matching x64/ARM64 hosts.
