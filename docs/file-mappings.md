# Files outside ASAR

`electron_app` accepts declared file or tree-artifact labels:

```starlark
extra_resources = {":settings": "config/settings.json"},
extra_files = {":notice": "licenses/NOTICE.txt"},
```

`extra_resources` copies beneath `resources/` on Linux/Windows and
`Contents/Resources/` on macOS. `extra_files` copies beneath the distribution root
on Linux/Windows and `Contents/` on macOS, matching
[electron-builder's content directories](https://www.electron.build/docs/contents/).
Both stay outside `app.asar`.

Mappings require normalized relative destinations. Tree contents retain relative
paths, including dotfiles. Assembly preserves executable status, normalizes modes
to 0755/0644 and timestamps to epoch. It rejects app/ASAR destinations, duplicate
paths, file/directory collisions and runtime-file replacement. Windows/macOS
collision checks ignore case. Raw directory symlinks in tree artifacts remain
unsupported; [Bazel tree artifacts do not support symlinks](https://bazel.build/rules/lib/builtins/actions#declare_symlink).

Declare internal resource links separately on Linux/macOS:

```starlark
extra_resources = {":settings": "versions/v1/settings.json"},
resource_symlinks = {"current": "versions/v1", "nested/config": "current"},
```

Targets are relative to the resource root. Links retain filesystem semantics,
including chains and directory aliases. Missing targets, escapes, cycles,
collisions and links into app/ASAR paths fail before assembly writes output.
Linux apps with links use a ZIP-backed `ElectronAppInfo` artifact, avoiding
unsupported symlinks in Bazel tree outputs. Release archives and DEB packaging
stream that ZIP; immutable imports validate its layout and CPU. macOS retains
links through signing and its app ZIP. Generated trees carry logical resource
links through `ElectronFileTreeInfo.symlink_manifest`; see
[file selection](file-selection.md). Windows junction/link installation remains
open.

The [a27aaca BB suite](https://formatjs.buildbuddy.io/invocation/8a023435-0143-4889-ae2c-0b44090de2ed)
passed actual app ZIP, immutable import, TAR and DEB action boundaries, including
relocated directory aliases and target updates observed through links. The
[seven cross-build variants](https://formatjs.buildbuddy.io/invocation/c0534670-f427-4854-b6bb-439abb92dd38)
and [four native host types](https://github.com/formatjs/rules_electron/actions/runs/42536976011)
passed. macOS native smoke checks both resource links after signing and ZIP
relocation, through Electron's filesystem API.

At runtime, `process.resourcesPath` locates extra resources. Its parent locates
extra files on all three platforms. The desktop example reads a packaged notice
there during native smoke.

[BB assembly tests](https://formatjs.buildbuddy.io/invocation/f79a67e5-511b-4ef9-99c7-a4f235c02e35)
and [seven cross-build variants](https://formatjs.buildbuddy.io/invocation/2c48cc35-4af3-4a3f-a72d-3334074ca928)
passed. [Native smoke](https://github.com/formatjs/rules_electron/actions/runs/42453918813)
passed on Linux x64, macOS ARM64 and Windows x64/ARM64, including installed DEB/NSIS
flows. Assembly tests cover file/tree layout on all platforms, relocation, ASAR
exclusion, executable modes, dotfiles and rejected app/runtime collisions.
