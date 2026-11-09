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

`admin_rights_required` lists Windows installer filenames requiring elevation.
The feed writes `isAdminRightsRequired: true` on those file entries, which the
pinned client's download helper preserves for `NsisUpdater`. Use it with machine-
scope NSIS packages and the declared native `resources/elevate.exe` bridge.
Other platforms and undeclared/duplicate filenames fail validation. This metadata
does not elevate the application itself.

External maps use gzip-compressed v2 JSON with content-defined gear chunks,
16–64 KiB except the final tail, and SHA-256 checksums. Boundaries depend on
content so unchanged data can be reused after byte insertions/deletions. The
updater's copy/download planner consumes the same v2 format; final SHA-512 still
verifies the complete downloaded artifact. Embedded AppImage maps require a
separate packaging stage.

The desktop example pins electron-updater 6.8.11 and its script-free npm closure
through an integrity-checked lockfile. Native smoke exercises discovery, channel
routing, artifact hashes and actual updater blockmap planning over local HTTP.
Its metadata fixture is not an installer. Separate [Linux DEB and RPM tests](linux-packages.md) use real v1/v2 packages,
hash rejection and installed-app upgrades.
[Windows NSIS smoke](windows-installers.md) adds real installer lifecycle and
differential range downloads. Other targets,
signature rejection and release-identity verification remain pending.

The macOS ARM64 lifecycle gate adds BB-signed v1/v2 ZIPs and a candidate signed
by a different public test key. Signing uses fixed certificate dates, a fixed
signing time and no timestamp service; the action checks repeated output bytes.
No release credentials enter those fixture actions. Native smoke tests corrupt
ZIP rejection, wrong-identity rejection, real Squirrel replacement/relaunch and
full v2 app behavior. It checks both installed versions with strict `codesign`
validation and an explicit requirement pinning the app identifier and public
fixture certificate. It does not modify keychains or system trust.

Electron 39's [pinned Squirrel verifier](https://github.com/Squirrel/Squirrel.Mac/blob/0e5d146ba13101a1302d59ea6e6e0b3cace4ae38/Squirrel/SQRLCodeSignature.m#L127)
checks candidates against the installed app's designated requirement. The
fixture pins a certificate hash; it does not use `anchor trusted`.
[Apple documents](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html)
that these requirements need no system trust grant. The
[3809857 BB cross-build](https://formatjs.buildbuddy.io/invocation/6f88f68a-a180-4f80-aa58-7bd146a55e2c)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42693629082)
passed, including every macOS lifecycle check without trust setup. Production
Developer ID/notarization acceptance remains unverified.

The Mac differential gate adds external v1/v2 ZIP blockmaps. A separate v1
installation seeds the declared v1 release ZIP into the pinned client's fixture
cache, then fetches both maps from the local feed. Every candidate ZIP request
must use HTTP ranges; transferred ZIP bytes must stay below half the full ZIP.
The client still verifies final SHA-512, and Squirrel must replace/relaunch the
app before strict signature and full v2 smoke checks pass. Ordinary full-download
installation remains a separate case. This measures reuse with an existing ZIP
cache; blockmap metadata bytes are excluded. The
[ab9307d BB build](https://formatjs.buildbuddy.io/invocation/0102a46c-6809-451a-a867-e432766d1cce)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42697882602)
passed. Mac ARM64 downloaded 486,177 of 285,561,263 ZIP bytes: 99.83% reuse, with
both full and differential replacement/relaunch and full v2 behavior verified.

Protocol references: [auto update](https://www.electron.build/v26/docs/features/auto-update/),
[channel routing](https://github.com/electron-userland/electron-builder/blob/v26.0.12/packages/electron-updater/src/providers/Provider.ts),
[external blockmap reader](https://github.com/electron-userland/electron-builder/blob/v26.0.12/packages/electron-updater/src/AppUpdater.ts).

The example uses the published 6.8.11 Linux package-manager detector. Version
6.6.2 throws when `which zypper` fails, before trying dnf on Fedora. The updated
client probes available managers independently. CI supplies only a headless
elevation adapter; dnf/dpkg perform real installation. Dependency tarballs remain
integrity-pinned, with no npm lifecycle scripts executed during builds.

[6.8.11 lifecycle validation](https://github.com/formatjs/rules_electron/actions/runs/42544004368)
passed all four native hosts: DEB and Fedora RPM install/update/removal, NSIS
differential installation on both Windows CPUs, plus macOS discovery. Compilation
and packaging ran on BB; the Fedora container only installed and executed outputs.

AppImages use `embedded_blockmaps` on `electron_update_feed`; the final artifact
already contains its raw-deflate v2 map and big-endian size trailer. The feed
validates coverage and emits `blockMapSize`. The [installed AppImage gate](https://github.com/formatjs/rules_electron/actions/runs/42556985004)
passed real client replacement on Linux x64, with FUSE launch, hash rejection,
versioned/custom filenames and 99.7% differential reuse. See [AppImage](appimage.md).

Generic HTTP publication uses `@rules_electron//electron/tools:publish_update`.
Run it explicitly from the BB Linux release workflow after building and downloading
the feed output. Build the publisher for Linux, independently of the feed's target
platform. Pass its absolute output directory as `--feed`:

```sh
bazel run --config=bb-workflow @rules_electron//electron/tools:publish_update -- \
  --feed "$release_feed_directory" --channel latest.yml \
  --destination https://releases.example.com/windows/arm64/ \
  --token-env RELEASE_TOKEN
```

Supply `RELEASE_TOKEN` privately to the release process. Its value never enters
rule attributes or artifact build actions. Omit `--token-env` for anonymous
endpoints. Publication is an explicit network side effect; artifact construction
remains hermetic. No external publication runs in ordinary CI.

The destination must support conditional HTTP PUT, HEAD and GET. Before making
requests, the tool snapshots the flat native feed, checks SHA-512/size metadata,
checks each external blockmap against payload bytes, and rejects extra files or
symlinks. Payloads and blockmaps upload before channel metadata, using
`If-None-Match: *`. Existing immutable objects are reused only after downloading
and verifying identical bytes. Rerunning resumes interrupted uploads.

An existing channel must expose a strong ETag. Its final write uses `If-Match`;
a new channel uses `If-None-Match: *`. Concurrent changes fail publication instead
of overwriting channel metadata. The release workflow chooses versions and must
serialize intended promotions. Redirects and asynchronous HTTP 202 responses fail.
HTTPS is required; `--allow-http-loopback` exists for socket-based CI tests only.
Object-store-specific APIs and credential-provider adapters remain separate
migration work. The [GitHub publication interface](github-publication.md) stages
multiple feeds through a verified draft release; its protocol validation is in
progress.

The [db220dc BB suite](https://formatjs.buildbuddy.io/invocation/dcd45a49-c63b-4107-a8fb-be76a3bcb6b0)
passed the public publisher executable against a local HTTP server: exact bytes
and ordering, idempotent retry, conflicting payloads, corrupt artifacts/blockmaps,
interrupted uploads, HTTP 202/redirect rejection, concurrent channel updates,
unsafe files and strong-ETag requirements. This proves protocol behavior without
publishing to an external release destination.
