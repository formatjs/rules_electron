# Npm runtime inputs

`npm_runtime` materializes an integrity-pinned npm lockfile v3 layout:

```starlark
# MODULE.bazel
npm_runtime = use_repo_rule("@rules_electron//electron:npm.bzl", "npm_runtime")
npm_runtime(
    name = "app_npm",
    lock = "//:package-lock.json",
    target_os = "linux",
    target_cpu = "arm64",
    target_libc = "glibc",
)

# electron_app input
srcs = {"@app_npm//:runtime": "node_modules"},
```

Repository fetching uses the lock's HTTPS archive URLs and SHA-256/384/512 SRI
hashes. Assembly reuses declared `electron_files` tooling and normalizes file
modes/timestamps. No npm executable,
dependency resolution, lifecycle scripts, PATH tools or host platform detection
run. Nested/scoped package paths retain the lock's Node resolution layout.

Packages marked `dev` are omitted by default; `include_dev = True` retains them.
`devOptional` packages remain production inputs. OS/CPU/libc restrictions require
explicit `target_os`, `target_cpu` or `target_libc` using npm names (`darwin`,
`win32`, `linux`; `x64`, `arm64`). Incompatible optional packages are omitted;
incompatible required packages fail. Use separate repositories and a target
`select` when different triples need different trees. Universal script-free
dependencies need no target attributes.

Production selection follows npm's [lockfile flags](https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json#packages).
The checked-in lock remains authoritative; regenerate it with npm when the
dependency graph changes, then review its versions and integrity hashes.

`strip_node_modules = False` retains the `node_modules/` prefix, useful for
declared Node tools. The default exposes its contents for the app mapping above.
Metadata rewriting remains separate: see [manifest overlays](metadata.md).

`npm_runtime` supports separately recorded `inBundle` dependencies. Their bytes
come from the nearest selected parent archive and its SRI; no separate child
download occurs. Bundled package name/version must match the lock, and the
manifest must resolve inside that archive owner. Missing owners or mismatched
identities fail fetching. `@app_npm//:bundled_packages.json` records each owner
and integrity hash. Development/platform omissions prune entire nested package
subtrees, including files already present in a parent tarball. Parent archives
extract before nested package overrides, independent of lock object order.

The BB fixture uses the pinned npm 11.4.2 archive and its 209 bundled package
records, including aliases and an explicit development omission. npm itself is
never executed. Hosted validation remains pending.

`npm_runtime` still rejects workspace/file/git links. Package-manager link
layouts, bin shims and install scripts remain unsupported by that fetcher.
Build native addons through declared Bazel
targets, then map their outputs into the app. General Node/V8 ABI addon tooling
and adapters for other npm providers remain open.

Use configured targets for workspace packages and generated code:

```starlark
load("@rules_electron//electron:npm.bzl", "electron_npm_package", "electron_npm_tree")

electron_npm_package(
    name = "native_package",
    package_json = "native-package/package.json",
    srcs = {
        "native-package/index.cjs": "index.cjs",
        ":native_addon": "addon.node",
    },
)

electron_npm_tree(
    name = "workspace_npm",
    packages = {":native_package": "node_modules/example-native"},
)

# App inputs:
srcs = {":workspace_npm": "node_modules"},
# electron_package_json inputs:
dependency_manifests = [":native_package"],
```

`electron_npm_package` accepts declared files/trees, including generated target
outputs, and requires a package name and exact SemVer. It normalizes and copies
the same `package.json` exposed by `ElectronNpmPackageInfo`. Package JSON is owned
by the rule; omit it from `srcs`. `dependency_manifests` rewrites production
workspace/file ranges from declared package JSON files or package providers.
`remove_scripts = True` strips package scripts; no lifecycle scripts run either
way. Directory manifests propagate through the package and assembled tree.

`electron_npm_tree` preserves explicitly supplied root, scoped, nested and alias
installation paths. Paths must start with `node_modules/`; its default output
strips that prefix, matching `npm_runtime`. Set `strip_node_modules = False` to
retain it. Packages do not acquire transitive dependencies implicitly: declare
the complete layout, including peer dependencies, through `packages`. Cyclic
workspace metadata can use original JSON files as version inputs rather than
introducing cyclic Bazel target dependencies. No resolver, hoister or filesystem
symlink layout runs during assembly. Provider-specific imports remain open.

The native example packages its target-built addon through these rules and
derives app dependency versions from that package provider. The
[6b6a46a BB suite](https://formatjs.buildbuddy.io/invocation/cabd145b-b737-4be4-9cc3-e187427982b3),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/a252d750-5e5c-452f-996c-7791bf054246)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42518647293)
passed, including both Windows compiler variants. Package tests cover generated
versions, nested aliases, immutable source manifests and directory propagation
into ASAR.

The desktop example consumes this public rule for electron-updater, PE tooling
and minimatch. Its updater lock includes development-only minimatch; native smoke
checks its absence while executing the real updater and addon.
[BB unit tests](https://formatjs.buildbuddy.io/invocation/f9613d76-439b-49bc-9258-5e411ec845a5),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/109ceb2b-a4a6-4c3c-8dfd-68578f094755)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42467272905)
passed, including both Windows compiler variants. Lock selection tests cover
development/optional packages, explicit target constraints and unsafe inputs.
