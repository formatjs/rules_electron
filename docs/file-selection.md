# File selection

`electron_files` creates a filtered tree from declared file/tree mappings:

```starlark
load("@rules_electron//electron:files.bzl", "electron_files")

electron_files(
    name = "renderer_files",
    srcs = {":renderer_bundle": "renderer"},
    patterns = ["**/*", "!**/*.map", "!**/development.txt"],
    file_matcher = ":file_matcher",
)

# electron_app input:
srcs = {":renderer_files": ""},
```

An empty destination mounts a tree at the collection root. App and standalone
ASAR `srcs` also accept empty destinations for trees. Regular files require a
nonempty filename. Selected destination collisions and file/directory conflicts
fail before copying.

Patterns use the [declared minimatch tool](file-patterns.md), after source trees
expand and destination prefixes apply. Empty patterns retain all regular files.
Nonempty patterns start with no selected files and apply inclusions/exclusions in
order. Use one collection per mapping when inputs need different filters.

Outputs retain relative paths and executable status, with normalized 0755/0644
modes and epoch timestamps. The resulting tree works with app `srcs`,
`extra_resources`, `extra_files` or standalone ASAR mappings. Filtering does not
read undeclared host paths. Directory symlinks remain unsupported; empty
source directories are omitted.

The generic renderer bundle contains development fixtures; its filtered view
excludes them. Native smoke checks both their absence and working renderer/IPC.
Hosted validation is pending.
