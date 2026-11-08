# Unpack patterns

`electron_app.asar_unpacked_patterns` and `electron_asar.unpacked_patterns`
select regular files for the unpacked sidecar. Supply a declared execution tool:

```starlark
load("@rules_electron//electron:matching.bzl", "electron_file_matcher")

electron_file_matcher(
    name = "file_matcher",
    node = "@nodejs_26_13_0//:node",
    modules = ":pinned_minimatch_modules",
)

# electron_app attributes:
asar_unpacked_patterns = ["**/*.{node,dll}", "!**/fixtures/**"],
file_matcher = ":file_matcher",
```

The modules tree retains `node_modules/minimatch` and its locked dependencies.
The example pins minimatch 10.2.4 and uses source-built hermeticbuild Node. No npm
installation or target executable runs in assembly actions.

Patterns match archive-relative POSIX paths, case-sensitively, with dotfiles
included. Globstars, braces, character classes and extglobs use minimatch itself.
Patterns apply in order: inclusion, exclusion, then explicit re-inclusion. A bare
directory name also selects its descendants. Selection starts empty; use `**/*`
before an exclusion when all other files should match.

Matching sees only declared regular files after tree expansion. It does not walk
the execution host's filesystem or select virtual ASAR links. Explicit
`asar_unpacked`/`unpacked` paths join the selection and remain unpacked even when a
pattern excludes them. Exact paths still fail when absent; patterns may match
nothing. App patterns require `asar=True`.

BB tests cover the real matcher grammar; native examples select unpacked addons
through patterns in both main and additional ASARs. Hosted validation is pending.
