# macOS icons

Set `electron_app.macos_icon` to a declared `.icns` file or generated ICNS target:

```starlark
macos_icon = ":app_icon",
```

Assembly checks container lengths, stages `Contents/Resources/app.icns`, updates
the main/helper bundles' `CFBundleIconFile` and clears inherited `CFBundleIconName`.
Icons are copied before bundle signing. Existing files at the staged main-icon
destination conflict with this mapping and fail assembly. The option requires a
macOS target; use `select` in shared app definitions.

Supply a valid multi-resolution ICNS asset. Assembly validates container framing;
it does not decode representations or convert PNG/SVG files. Generate those assets
with declared Bazel tools. No host image utility or runtime executable runs during
assembly. [Apple's bundle icon contract](https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/CoreFoundationKeys.html)
defines the resource-directory lookup.

The example generates a fixed gray PNG-backed ICNS on BB with pinned Python. Its
native macOS smoke uses `NSWorkspace.iconForFile:` to check icon pixels, then retains the
existing deep/strict signature verification.

[BB tests](https://formatjs.buildbuddy.io/invocation/f5378f61-887e-441f-8e67-b388a7abe2fa),
[seven cross-build variants](https://formatjs.buildbuddy.io/invocation/26d6eb66-513c-4f87-a05a-8ad4ab9788f6)
and [native smoke](https://github.com/formatjs/rules_electron/actions/runs/42459477459)
passed. macOS checks the actual bundle icon bitmap through AppKit, alongside
URL dispatch and ASAR corruption/signature checks.
