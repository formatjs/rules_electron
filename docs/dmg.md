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
    licenses = {"//legal:license.txt": "en_US"},
    license_labels = "//legal:labels.json",
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
volume layout.

`background_image` accepts a declared PNG, up to 64 MiB and 8192 pixels per axis.
It requires `finder_window`, overrides the background color and copies unchanged
bytes to `.background.png`. Its Carbon alias uses the explicit volume name/date
and a path inside that volume, without build paths, assumed mount points or host
file IDs. The writer
reads the background's catalog ID/date from its first generated HFS+ image,
finalizes the alias, then rebuilds and verifies unchanged catalog identity before
UDIF conversion. No mounting or target execution is involved. A path-based form also appears in
[Chromium's Linux-compatible generator](https://chromium.googlesource.com/chromium/src/+/9c363bb2863cd723978a8a245719389a7bf1c20e/chrome/installer/mac/generate_dsstore.py).
BB tests decode the packaged alias and image bytes, check actual catalog IDs/dates and
compare relocated builds. Native smoke resolves the packaged background
alias through macOS descriptors and compares captured Finder-window pixels with
the declared PNG through native color management. The picture getter is recorded
as a diagnostic; it throws `-10000` on the hosted Finder even when the generated
alias resolves. The [74601b7 BB suite](https://formatjs.buildbuddy.io/invocation/6452fea3-0ac9-41ca-b955-5d6f01d02dc0),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/4e19bcdb-a3a6-4a34-8bed-30313e3bfc2b)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42730207912)
passed. The macOS host resolved the packaged alias and compared three clear
Finder-window samples with the same PNG through native color management:
all samples were identical, `[187, 187, 187, 255]`. Screenshots stay temporary;
only numeric samples enter logs. Existing signatures and updater lifecycle also
passed.

## License agreements

`licenses` maps declared UTF-8 `.txt` or `.rtf` files to explicit locales.
`license_default_language` defaults to `en_US` and must appear in that mapping.
The [locale table](../electron/private/dmg_licenses.py) includes English, French,
German, Japanese, Korean and Chinese regional IDs. Text uses that locale's legacy
encoding when representable, otherwise Unicode RTF. Declared RTF bytes stay
unchanged. No host locale or filename discovery supplies
inputs.

`license_labels` optionally provides a JSON object keyed by those same locales.
Each locale can override `languageName`, `agree`, `disagree`, `print`, `save` and
`message`. Defaults use the locale name and English controls. Labels must fit
255 bytes in that locale's legacy encoding. License inputs allow 2 MiB per file,
16 MiB total and at most 32 entries; labels allow 64 KiB and final XML 64 MiB.

```json
{"en_US":{"languageName":"English","agree":"Agree","message":"Read license before installing."}}
```

The separate `ElectronDmgLicense` action adds `LPic`, `STR#` and `TEXT`/`RTF ` resources
to the unsigned image. License edits do not change filesystem-action inputs.
Compressed disk bytes and block maps stay unchanged; image identity includes the
new XML. Signed images, existing license resources, malformed bounds and
output/input aliases fail. Sign/notarize only after this stage.

The resource mapping follows the [dmg-license format](https://github.com/argv-minus-one/dmg-license/blob/master/src/makeLicensePlist.ts).
BB tests decode mappings and labels independently, preserve actual disk bytes,
cover Unicode/surrogates and compare relocated/reordered inputs. Native smoke
requires the sample license to be displayed, refusal to prevent mounting, and
acceptance to mount the same BB image. The
[e2f8568 suite](https://formatjs.buildbuddy.io/invocation/b9ae499d-447b-41ed-af02-56fa945538b9)
and [seven cross-builds](https://formatjs.buildbuddy.io/invocation/048324fe-3ebc-4e1b-b38d-9ecac53f9b1f)
passed. Its [native macOS job](https://github.com/formatjs/rules_electron/actions/runs/42740919873)
decoded the English `TEXT` body, refused attachment after decline (exit 1, no
mount), then accepted and mounted (exit 0). Readonly Finder pixels, app signature,
runtime and updater checks passed. That workflow's Windows jobs failed the
separate NSIS consent observer. RTF-only and non-English consent remain unproven;
native AppKit decoding alone does not prove a visible agreement.

The manual `dmg_license_probe` workflow input tests a previously verified BB
image with the workflow's current macOS harness. Linux performs authenticated,
commit-bound artifact retrieval; the matching Mac host only inspects the image.
Probe results do not publish normal native-smoke commit status.

`electron_dmg_license` creates another legal variant without rebuilding the
filesystem. Its `image` accepts an `electron_dmg` target (using that target's
unlicensed base) or a raw unsigned, unlicensed `.dmg`. It shares the `licenses`,
`license_default_language` and `license_labels` attributes above. Signed or
already-licensed raw files fail. `ElectronDmgInfo` exposes `image`/`unlicensed`;
the original rule also exposes the `unlicensed` output group.

```starlark
load("@rules_electron//electron:dmg.bzl", "electron_dmg_license")

electron_dmg_license(
    name = "release_japanese",
    image = ":release_dmg",
    licenses = {"//legal:license.rtf": "ja_JP"},
    license_default_language = "ja_JP",
)
```

The example's canonical Unicode RTF variant uses the existing filesystem image
and a Japanese default locale. Hosted action inspection requires one filesystem
action feeding both license variants. Native RTF consent remains pending; select
`dmg_fixture=release_dmg_rtf.dmg` with the manual probe to inspect it.

Metadata uses checksum-pinned MIT-licensed `ds_store` 1.3.3 and `mac_alias` 2.2.2
Python sources. No host alias discovery, Finder, mounting or AppleScript
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
