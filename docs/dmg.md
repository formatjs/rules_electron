# macOS disk images

```starlark
load("@rules_electron//electron:dmg.bzl", "electron_dmg")

electron_dmg(
    name = "release",
    app = ":app",
    volume_name = "Sample Desktop",
    source_date_epoch = 1577836800,
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
release. DMG signing/notarization, Finder backgrounds/icons/layout and license
dialogs remain separate gaps. The example's app carries ad hoc signatures.

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
