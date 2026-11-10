# macOS disk images

```starlark
load("@rules_electron//electron:dmg.bzl", "electron_dmg")

electron_dmg(
    name = "release",
    app = ":app",
    volume_name = "Sample Desktop",
    volume_icon = "//assets:volume.icns",
    source_date_epoch = 1577836800,
    finder_window = [120, 140, 600, 360],
    app_position = [140, 160],
    applications_position = [460, 160],
    icon_size = 112,
    text_size = 12,
    background_color = "#ddeeff",
    background_image = "//assets:installer-background.png",
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
volume layout. License dialogs remain separate work.

`background_image` accepts a declared PNG, up to 64 MiB and 8192 pixels per axis.
It requires `finder_window`, overrides the background color and copies unchanged
bytes to `.background.png`. Its Carbon alias uses the explicit volume name/date
and a path inside that volume, without build paths, host file IDs or filesystem
discovery. The path-based form also appears in
[Chromium's Linux-compatible generator](https://chromium.googlesource.com/chromium/src/+/9c363bb2863cd723978a8a245719389a7bf1c20e/chrome/installer/mac/generate_dsstore.py).
BB tests decode the packaged alias and image bytes, check volume dates and
compare relocated builds. Native smoke reads Finder's resolved background
picture and requires the mounted image's exact file. Background-image support
awaits hosted validation.

Metadata uses checksum-pinned MIT-licensed `ds_store` 1.3.3 and `mac_alias` 2.2.2
Python sources. No alias filesystem discovery, Finder, mounting or AppleScript
runs in artifact actions. Geometry/color inputs and metadata bytes participate
in deterministic image identity. BB tests decode the packaged settings and
auto-open catalog ID, preserve app seals and compare relocated input bytes.
Native smoke reads settings through Finder without changing them. The
[02da44f BB suite](https://formatjs.buildbuddy.io/invocation/72077f05-f043-461a-9c1a-30812c6c80e5),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/ca91b301-efe5-433b-9f40-963cc2ec0e8c)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42720828995)
passed window geometry, icon positions/sizes, background color, strict app
signatures and the full existing installer/update smoke. The native geometry
check converts Cocoa bounds using the actual display height. See the
[codec contract](https://ds-store.readthedocs.io/en/latest/index.html).

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

`volume_icon` accepts a declared ICNS file. The writer validates and copies its
bytes to `.VolumeIcon.icns` and sets the HFS+ root folder's custom-icon flag.
The signed app bundle stays immutable; icon bytes participate in volume identity.
BB tests read catalog flags independently, compare relocated image bytes and
reject malformed icons or output/input aliases. Native smoke asks NSWorkspace
for the mounted volume icon and compares its rendered pixels against the same
declared app icon through native color management. Exact ICNS byte equality is
also required. The [69c3287 suite](https://formatjs.buildbuddy.io/invocation/a1cf3460-1178-4f32-acd9-3738a09b3bfb),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/d86d10a4-aba4-41c4-ba30-d376cf53a1e1)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42724309931)
passed. The flag follows [Apple TN1150](https://developer.apple.com/library/archive/technotes/tn/tn1150.html).

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
