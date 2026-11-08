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

Workspace/file/git dependencies, separately recorded bundled dependencies,
package-manager link layouts, bin shims and install scripts are unsupported.
Build native addons through declared Bazel
targets, then map their outputs into the app. General Node/V8 ABI addon tooling
and adapters for other npm providers remain open.

The desktop example consumes this public rule for electron-updater, PE tooling
and minimatch. Its updater lock includes development-only minimatch; native smoke
checks its absence while executing the real updater and addon. Hosted validation
of this public import rule is pending.
