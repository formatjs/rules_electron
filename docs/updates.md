# electron-updater

Generate client configuration before app signing:

```starlark
load("@rules_electron//electron:update.bzl", "electron_update_config", "electron_update_feed")

electron_update_config(
    name = "update_config",
    url = "https://updates.example.com/linux/x64/",
    cache_name = "example-updater",
    channel = "latest",
)
```

Map `:update_config` to `app-update.yml` in `electron_app.extra_resources`. Include
`electron-updater` and its runtime dependencies in the app's npm inputs. The rule
does not inject JavaScript or start an updater automatically.

Generate release metadata from final artifacts, after signing:

```starlark
electron_update_feed(
    name = "release_feed",
    artifacts = {":signed_installer": "Example-1.2.3-x64.exe"},
    package_json = "package.json",
    platform = "windows",
    architecture = "x64",
    release_date = "2026-01-02T03:04:05Z",
    blockmaps = ["Example-1.2.3-x64.exe"],
)
```

The output directory contains unchanged artifact bytes, SHA-512/size metadata,
the channel file and requested external `.blockmap` files. Release time is
explicit, so identical inputs produce identical output bytes. JSON syntax is
used in `.yml` files; electron-updater's YAML parser accepts it.

Channel filenames follow electron-updater's routing:

| Target | Default channel file |
| --- | --- |
| Windows x64/ARM64 | `latest.yml` |
| macOS x64/ARM64 | `latest-mac.yml` |
| Linux x64 | `latest-linux.yml` |
| Linux ARM64 | `latest-linux-arm64.yml` |

Use separate Windows/macOS CPU feed URLs unless the release workflow deliberately
merges compatible artifacts. Keep the same updater cache name across versions.
`publisher_names` records the expected Windows signing certificate publisher names;
it does not sign artifacts. `staging_percentage` emits optional rollout metadata.

External maps use gzip-compressed v2 JSON with content-defined gear chunks,
16–64 KiB except the final tail, and SHA-256 checksums. Boundaries depend on
content so unchanged data can be reused after byte insertions/deletions. The
updater's copy/download planner consumes the same v2 format; final SHA-512 still
verifies the complete downloaded artifact. Embedded AppImage maps require a
separate packaging stage.

The desktop example pins electron-updater 6.8.11 and its script-free npm closure
through an integrity-checked lockfile. Native smoke exercises discovery, channel
routing, artifact hashes and actual updater blockmap planning over local HTTP.
Its metadata fixture is not an installer. A separate [Linux DEB test](linux-packages.md)
uses real v1/v2 packages, hash rejection and installed-app upgrades.
[Windows NSIS smoke](windows-installers.md) adds real installer lifecycle and
differential range downloads. Other targets,
signature rejection and release-identity verification remain pending.

Protocol references: [auto update](https://www.electron.build/v26/docs/features/auto-update/),
[channel routing](https://github.com/electron-userland/electron-builder/blob/v26.0.12/packages/electron-updater/src/providers/Provider.ts),
[external blockmap reader](https://github.com/electron-userland/electron-builder/blob/v26.0.12/packages/electron-updater/src/AppUpdater.ts).

The example uses the published 6.8.11 Linux package-manager detector. Version
6.6.2 throws when `which zypper` fails, before trying dnf on Fedora. The updated
client probes available managers independently. CI supplies only a headless
elevation adapter; dnf/dpkg perform real installation. Dependency tarballs remain
integrity-pinned, with no npm lifecycle scripts executed during builds.
