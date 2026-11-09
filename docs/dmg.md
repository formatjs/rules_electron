# macOS disk images

```starlark
load("@rules_electron//electron:dmg.bzl", "electron_dmg")

electron_dmg(
    name = "release",
    app = ":app",
    volume_name = "Sample Desktop",
    source_date_epoch = 1577836800,
    finder_window = [120, 140, 600, 360],
    app_position = [140, 160],
    applications_position = [460, 160],
    icon_size = 112,
    text_size = 12,
    background_color = "#ddeeff",
)
```

The rule cross-packages a macOS `ElectronAppInfo` on BB Linux. Pinned xorriso and
UDIF converter sources compile with native Bazel C actions and declared zlib.
No configure, Make, CMake, mounted image or target executable runs during builds.

Output is a read-only, zlib-compressed UDIF disk image containing an HFS+ volume,
the app bundle and a standard `/Applications` link. `applications_link = False`
omits that link. Volume labels allow up to 32 UTF-8 bytes. Dates and ownership
are explicit; filesystem and UDIF identities derive from input bytes. User
configuration, host tools, filesystem times and libc PRNG state do not supply
image inputs. Existing app file bytes, modes and relative links survive staging.

Sign and notarize the app before immutable import when preparing a production
release. The example's app carries ad hoc signatures.

`finder_window` enables a deterministic `.DS_Store` and HFS+ auto-open folder.
It declares Cocoa x, y, width and height, with a bottom-left screen origin.
App/Applications icon positions use centers
inside that window; `icon_size` allows 16..512 pixels and `text_size` 10..16.
`background_color` accepts `#RRGGBB`. Omitting `finder_window` retains the plain
volume layout. Background images, custom volume icons and license dialogs
remain separate gaps.

Metadata uses checksum-pinned MIT-licensed `ds_store` 1.3.3 and `mac_alias` 2.2.2
Python sources. No alias filesystem discovery, Finder, mounting or AppleScript
runs in artifact actions. Geometry/color inputs and metadata bytes participate
in deterministic image identity. BB tests decode the packaged settings and
auto-open catalog ID, preserve app seals and compare relocated input bytes.
Native smoke reads settings through Finder without changing them. Hosted
validation remains pending. See the [codec contract](https://ds-store.readthedocs.io/en/latest/index.html).

BB tests independently decode UDIF block maps, check compressed/uncompressed
CRC32 values, compare relocated ZIP/tree inputs, and read the image payload with
xorriso. The native macOS smoke verifies/mounts the BB image read-only, copies
the app, checks code signatures, then launches Electron with renderer/addon
checks. [BB tests](https://formatjs.buildbuddy.io/invocation/85851da1-bece-4be0-b8b7-853614f83011),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/576b1a73-ee26-4463-8fa6-f0b1c7dad45b)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42680079490)
passed. The macOS ARM64 host verified/mounted the image, checked strict app
signatures and launched the copied app. The writer leaves regular-file Finder
metadata empty; adding default type/creator codes invalidates strict signatures.

## Release clients

```starlark
load("@rules_electron//electron:release.bzl", "electron_macos_dmg_release_tool")

electron_macos_dmg_release_tool(
    name = "release_dmg",
    signer = "@rcodesign_linux_x64//:rcodesign",
)
```

Run on the BB release client, outside cacheable artifact actions:

```sh
bazel run --config=bb-workflow //:release_dmg -- \
  --input unsigned.dmg --output notarized.dmg \
  --identifier org.example.sample \
  --certificate-env RELEASE_CERTIFICATE_FILE --key-env RELEASE_PRIVATE_KEY_FILE \
  --password-env RELEASE_KEY_PASSWORD --ca-file apple-roots.pem \
  --expected-leaf-sha256 "$EXPECTED_LEAF_SHA256" --expected-team-id "$EXPECTED_TEAM_ID" \
  --signing-time 2026-11-09T01:02:03Z --timestamp-url https://tsa.example.com/ \
  --api-key-env APPLE_API_KEY_FILE
```

The client shares the app release client's real OpenSSL preflight: leaf pin,
single team ID, explicit roots, encrypted key unlock and public-key match.
The timestamp URL and identifier must be explicit. It requires Developer ID
policy, then waits for accepted notarization and staples the image. Only the
final DMG is committed; compute update hashes after this stage.

`electron_macos_dmg_signing_tool` stops after signing and does not accept notary
credentials. `electron_macos_dmg_notarization_tool` accepts an already signed
DMG, `--input`, `--output`, `--api-key-env` and optional `--max-wait-seconds`.
Every client requires a declared execution backend; keys enter through runtime
environment names, without inherited credentials or tool configuration in child
processes. Input artifacts remain unchanged.

Signing preserves the image prefix and all footer fields except embedded
signature location/size. Notarization additionally preserves every existing
signature blob; only the ticket slot can change. Duplicate, overlapping,
truncated or malformed signature layouts fail. Output races preserve the
competing file. These checks protect artifact bytes, and do not verify CMS or
Apple ticket trust independently of the declared backend.

Tests use real OpenSSL and real rcodesign layouts with simulated certificate
signature/TSA/Apple boundaries. Live Developer ID/TSA/Apple interoperability and
production native trust remain unverified.
