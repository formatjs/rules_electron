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
expand and destination prefixes apply. Empty patterns retain all files and
declared empty directories.
Nonempty patterns start with no selected files and apply inclusions/exclusions in
order. Use one collection per mapping when inputs need different filters.

Outputs retain relative paths and executable status, with normalized 0755/0644
modes and epoch timestamps. The resulting tree works with app `srcs`,
`extra_resources`, `extra_files` or standalone ASAR mappings. Filtering does not
read undeclared host paths. Directory symlinks remain unsupported.

Use `directories = ["renderer/cache"]` to declare empty output directories;
the same patterns filter those paths. Bazel does not reliably preserve bare
empty directories inside tree inputs. Generated-tree rules can return
`ElectronFileTreeInfo(directory_manifest = file)` from `electron/files.bzl`,
where `file` is a declared JSON list of normalized tree-relative directory paths.
The manifest must be a separate output, outside the tree. `electron_files`
propagates this metadata; app/ASAR rules consume it. App assembly also carries
directory metadata into release ZIP/tar.gz archives and DEB/NSIS packaging.
No marker files enter the app. Immutable prepackaged tree imports still need
their own directory-manifest interface.

The generic renderer bundle contains development fixtures; its filtered view
excludes them. Native smoke checks both their absence and working renderer/IPC.
Hosted [unit tests](https://formatjs.buildbuddy.io/invocation/8b1dfd53-a7b2-4d11-bc43-31757b3ae171)
and [seven cross-builds](https://formatjs.buildbuddy.io/invocation/7ad6bac8-00b0-45be-980b-e133206ae3d6)
passed. [Native smoke](https://github.com/formatjs/rules_electron/actions/runs/42465475900)
passed on Linux x64, macOS ARM64 and Windows x64/ARM64, including both Windows
compiler variants.
