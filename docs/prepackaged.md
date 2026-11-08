# Prepackaged apps

`electron_prepackaged_app` imports an existing app tree artifact or macOS `.app`
ZIP into `ElectronAppInfo`. Archives, DEB and NSIS rules accept it directly.

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
packaging. Hosted unit, cross-build and native validation are pending.
