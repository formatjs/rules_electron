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

External maps use gzip-compressed v2 JSON with fixed 64 KiB chunks. They support
the updater's copy/download planner; content-defined chunks may reuse more bytes
after insertions. Embedded AppImage maps require a separate packaging stage.

The desktop example pins electron-updater 6.6.2 and its script-free npm closure
through an integrity-checked lockfile. Native smoke exercises discovery, channel
routing, artifact hashes and actual updater blockmap planning over local HTTP.
Its metadata fixture is not an installer. Install, restart, signature rejection
and installed-app upgrade tests remain pending with the installer/signing work.

Protocol references: [auto update](https://www.electron.build/v26/docs/features/auto-update/),
[channel routing](https://github.com/electron-userland/electron-builder/blob/v26.0.12/packages/electron-updater/src/providers/Provider.ts),
[external blockmap reader](https://github.com/electron-userland/electron-builder/blob/v26.0.12/packages/electron-updater/src/AppUpdater.ts).
