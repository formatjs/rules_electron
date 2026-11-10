# MSIX App Installer updates

`electron_msix_appinstaller` writes a deterministic `.appinstaller` descriptor
from the final MSIX's embedded identity. It runs on BB Linux with declared Python
and MSIX inputs. No Windows SDK tool, signing key, clock or network enters this
action. The MSIX bytes remain unchanged.

```starlark
load("@rules_electron//electron:msix.bzl", "electron_msix_appinstaller")

electron_msix_appinstaller(
    name = "update",
    package = ":signed_msix",
    appinstaller_uri = "https://updates.example.com/windows/arm64/latest.appinstaller",
    package_uri = "https://updates.example.com/windows/arm64/Example-2.0.0.msix",
    hours_between_update_checks = 12,
    automatic_background_task = True,
)
```

Name, publisher, package version and CPU come from `AppxManifest.xml` inside the
package. The descriptor version defaults to that package version;
`appinstaller_version` overrides it with four numeric components. This validates
metadata, not package signatures or certificate trust. Deploy final signed MSIX
bytes with the exact identity and filename referenced by the descriptor.

The rule emits Microsoft's
[2021 schema](https://learn.microsoft.com/en-us/windows/msix/app-installer/how-to-create-appinstaller-file).
`check_on_launch` controls `OnLaunch`; its default interval is 24 hours, with
0–255 accepted. `show_prompt` and `update_blocks_activation` declare launch
policy; blocking requires a prompt. `automatic_background_task` enables the
background element. `force_update_from_any_version` explicitly permits downgrades.
`update_uris` and `repair_uris` accept up to ten distinct fallback URLs each.
Windows owns scheduling, prompts and policy enforcement; see
[update settings](https://learn.microsoft.com/en-us/windows/msix/app-installer/update-settings).

URLs require HTTPS without credentials, query or fragment. Percent-encode Unicode
or spaces. `allow_http_loopback` exists for explicit native fixtures. Use separate
CPU URLs unless distributing an MSIX bundle; this rule currently emits
`MainPackage`, not `MainBundle` or dependency/optional-package sets.

Publish package bytes before promoting the descriptor. This rule neither uploads
nor installs them. App Installer uses Windows deployment APIs; it does not make
MSIX an electron-updater installer. Store distribution remains a separate flow.

`@rules_electron//electron/tools:publish_appinstaller` performs an explicit S3
release operation from BB Linux:

```sh
bazel run --config=bb-workflow @rules_electron//electron/tools:publish_appinstaller -- \
  --descriptor "$appinstaller_file" --package "$signed_msix" \
  --destination https://sample-updates.s3.us-west-2.amazonaws.com/windows/arm64/ \
  --region us-west-2
```

Credentials and multipart options follow the [S3 publisher](s3-publication.md).
Inputs must be regular files. The client snapshots their bytes and compares all
four package identity fields before contacting the service. Object names come
from public descriptor/package URLs; local Bazel output names may differ. Map
those public URLs to the chosen destination prefix. It uploads MSIX first with
`If-None-Match: *`, verifies identical existing bytes, then promotes the descriptor
with a strong ETag condition. Races stop promotion. Both upload modes set explicit
`application/msix` and `application/appinstaller` content types. This operation
does not validate certificate trust or publish dependency/bundle sets.

The [2b99e00 BB suite](https://formatjs.buildbuddy.io/invocation/17a41b65-4f45-4eba-9a98-a71e8f112e4f)
and [seven cross-builds](https://formatjs.buildbuddy.io/invocation/85bff46d-ad69-4aad-b284-30b91e75e3d8)
passed. Tests check identity, policy, URL boundaries, immutable inputs,
relocation/mtime stability and UTF-8/UTF-16 manifests. Native x64/ARM64
fixtures serve only unchanged BB outputs on loopback, install v1 through App
Installer, adopt its URI through `GetAppInstallerInfo`, update to v2, launch real
Electron and remove the package. Existing signature/activation tests remain
separate. [All four native hosts passed](https://github.com/formatjs/rules_electron/actions/runs/42767185353),
including the complete handoff on Windows x64/ARM64. The
[3445e4f BB suite](https://formatjs.buildbuddy.io/invocation/21a9f3d8-4d73-4216-b158-ce2463d2c854)
passed the public publication command against a signature-verifying server:
exact bytes/names, MIME, ordering, retries, identity rejection and channel races.
No live release was published.

An additional native gate now checks Windows'
[`CheckUpdateAvailabilityAsync`](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.package.checkupdateavailabilityasync?view=winrt-28000)
for no updates, an available v2, then no updates after installation. It uses
`PackageManager.FindPackageForUser` rather than the documented unsupported
`Package.Current` path. This discovery gate is pending. The short fixture does not prove background timing, prompt UX, fallback
server failover or production certificate trust.
