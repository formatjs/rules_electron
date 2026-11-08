# macOS URL schemes

Declare URL handlers on `electron_app`:

```starlark
macos_protocols = {"Example Desktop": ["example-desktop"]},
macos_protocol_roles = {"Example Desktop": "Viewer"},
```

Assembly writes `CFBundleURLTypes` to the main bundle before signing. Helpers
receive no URL handlers. Names and schemes sort deterministically; schemes
normalize to lowercase. Duplicate schemes, invalid URI schemes, unknown roles
and roles without a matching name fail assembly. These options require macOS.

Roles: `Editor` (default), `Viewer`, `Shell`, `QLGenerator`, `None`.
Handle Electron's `open-url` event before `app.whenReady()`. URL metadata does not
install runtime listeners or override the user's default-handler preferences.

The desktop example declares `sample-desktop`. Its native macOS smoke registers
the relocated bundle with LaunchServices, selects its handler, opens a fresh URL
through `/usr/bin/open`, checks delivery to Electron, restores any prior handler
and unregisters the bundle. Compilation and bundle
assembly stay on BuildBuddy. Native smoke validation is pending.
