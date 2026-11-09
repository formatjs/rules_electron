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
read undeclared host paths. Raw directory symlinks remain unsupported inside
Bazel tree artifacts.

Use `directories = ["renderer/cache"]` to declare empty output directories;
the same patterns filter those paths. Bazel does not reliably preserve bare
empty directories inside tree inputs. Generated-tree rules can return
`ElectronFileTreeInfo(directory_manifest = file)` from `electron/files.bzl`,
where `file` is a declared JSON list of normalized tree-relative directory paths.
The manifest must be a separate output, outside the tree. `electron_files`
propagates this metadata; app/ASAR rules consume it. App assembly also carries
directory metadata into release ZIP/tar.gz archives and DEB/NSIS packaging.
No marker files enter the app. Prepackaged imports inherit metadata from app/tree
providers; external imports can supply an explicit `directory_manifest` JSON
file. Import validation checks paths and collisions without rewriting app bytes.

Use `symlinks = {"renderer/current": "renderer"}` for logical links. Targets
are collection-root-relative; an empty target means the collection root.
Generated rules can return `ElectronFileTreeInfo(symlink_manifest = file)` with
a separate JSON object using the same mapping. Tree outputs contain ordinary
files and directories only. `electron_files` remounts and filters link paths,
then writes selected links to separate metadata. Selected links whose targets
were excluded fail before copying.

Standalone ASAR and `electron_app(asar = True)` consume this metadata as virtual
links. Linux/macOS plain app inputs, `extra_resources` and `extra_files`
materialize filesystem links in app ZIPs. Windows filesystem links currently
fail explicitly; ASAR virtual links work on Windows. Missing targets, cycles, escapes and collisions fail
before assembly writes output. Consumers must preserve the provider alongside
the tree; copying only `DefaultInfo.files` drops logical link metadata.

The initial generated-link [BB tests](https://formatjs.buildbuddy.io/invocation/59ed27a9-34ff-45c9-af55-3e401e25a01b)
and [seven cross-builds](https://formatjs.buildbuddy.io/invocation/9d7f8d48-1b38-4b5f-afba-34c30a596dda)
passed, including ASAR and resource ZIP/import/TAR/DEB action boundaries.
Native generated-link smoke remains unverified.

The generic renderer bundle contains development fixtures; its filtered view
excludes them. It also declares an empty renderer directory and an empty extra
resource directory. Native smoke checks both directories with `fs.readdirSync`,
alongside exclusions and working renderer/IPC. Those new directory checks await
hosted results.
Hosted [unit tests](https://formatjs.buildbuddy.io/invocation/8b1dfd53-a7b2-4d11-bc43-31757b3ae171)
and [seven cross-builds](https://formatjs.buildbuddy.io/invocation/7ad6bac8-00b0-45be-980b-e133206ae3d6)
passed. [Native smoke](https://github.com/formatjs/rules_electron/actions/runs/42465475900)
passed on Linux x64, macOS ARM64 and Windows x64/ARM64, including both Windows
compiler variants.
