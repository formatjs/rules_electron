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
paths, file/directory collisions and runtime-file replacement. Windows collision
checks ignore case. Directory symlinks in trees remain unsupported.

At runtime, `process.resourcesPath` locates extra resources. Its parent locates
extra files on all three platforms. The desktop example reads a packaged notice
there during native smoke. Hosted validation for this addition is pending.
