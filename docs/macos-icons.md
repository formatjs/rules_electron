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
existing deep/strict signature verification. Hosted validation is pending.
