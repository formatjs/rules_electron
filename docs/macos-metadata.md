# macOS application metadata

Pass a declared property list to `electron_app`:

```starlark
macos_extra_plist = "document-types.plist",
```

Its root must be a dictionary. Fields replace matching main-bundle Info.plist
fields before signing; nested dictionaries and arrays replace whole values.
Helpers receive no extra fields. Source files remain unchanged. This option
requires a macOS target.

App identity, version, package type, app icons, URL handlers and ASAR integrity
remain owned by their existing rule attributes. Overriding those fields fails.
Entitlements stay in `macos_entitlements` and `macos_entitlements_inherit`.

Use [CFBundleDocumentTypes](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundledocumenttypes)
for supported documents and [UTExportedTypeDeclarations](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/understanding_utis/understand_utis_declare/understand_utis_declare.html)
for application-owned types. Document icon names refer to resources staged in
`Contents/Resources`; the example uses its declared `app.icns`.

The [generic example](../examples/desktop/document-types.plist) declares an Editor
for `org.example.sample-desktop.document`, the `sample-desktop` extension, MIME
type and document icon. Handle Electron's `open-file` event before
`app.whenReady()`. Metadata registers capabilities; the application handles the
document contents.

BB tests cover metadata, source preservation, archive bytes, helper isolation and
rejected identity overrides. The macOS ARM64 smoke registers an isolated bundle,
checks the document icon, opens a Unicode filename through LaunchServices and
checks delivery and contents. It unregisters and removes the bundle afterward.
Native document validation is pending.
