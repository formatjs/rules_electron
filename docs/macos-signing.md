# macOS signing settings

`electron_app` accepts declared XML entitlement files and hardened-runtime flags:

```starlark
electron_app(
    name = "app",
    # Other app inputs omitted.
    macos_signer = ":rcodesign",
    macos_entitlements = "main.plist",
    macos_entitlements_inherit = "nested.plist",
    macos_hardened_runtime = True,
)
```

Main entitlements apply to the app executable. Inherited entitlements apply to
nested Mach-O executables, frameworks, libraries and addons. Each gets an
explicit bundle-relative rcodesign scope; settings do not depend on implicit
inheritance. Hardened runtime sets the `runtime` signature flag on these files
and the main bundle. Symlink aliases do not create duplicate signing settings.

Entitlement inputs must be XML plist dictionaries. Omitting either input adds
no entitlement override for its scope. Choose policy for the app's actual JIT,
native-addon and library requirements; the example's policy is a test fixture.
These settings require a macOS target. Assembly applies fuses/metadata before
signing, then creates the deterministic bundle ZIP.

Signing uses the declared execution-platform rcodesign, an empty configuration,
explicit environment and disabled timestamping. This stage signs ad hoc. It
does not accept release credentials; Developer ID, release timestamping,
notarization and stapling remain open. Release credentials belong outside
ordinary cacheable actions, and updater hashes must follow final release signing.

Native smoke checks Apple's deep/strict verification, entitlements and runtime
flags on the main app, helpers, framework and both addon locations, then launches
the app and exercises renderer/IPC/addons.
[BB tests](https://formatjs.buildbuddy.io/invocation/9ceb90ad-42b6-4c2e-be5c-28150b324ff2),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/01719356-5309-4cfb-bb95-a27255b9c16c)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42470400381)
passed. The macOS ARM64 host checked eight signed entities and launched the app
with its real renderer and native addon.

The scope contract follows [rcodesign's settings model](https://docs.rs/apple-codesign/0.29.0/apple_codesign/enum.SettingsScope.html).

The release adapter must override rcodesign 0.29's wall-clock signing time and
default HTTP timestamp URL. Its `--for-notarization` mode requires a Developer ID
certificate and timestamp, and enables hardened runtime across signed Mach-O
files. These checks do not replace final native trust verification. The pinned
`verify` command only verifies Mach-O files and warns that verification is
incomplete; it cannot serve as the sole bundle release gate. See the
[pinned CLI source](https://github.com/indygreg/apple-platform-rs/blob/apple-codesign/0.29.0/apple-codesign/src/cli/mod.rs).

## Notarization client

Declare an execution-platform rcodesign 0.29 backend explicitly:

```starlark
load("@rules_electron//electron:release.bzl", "electron_macos_notarization_tool")

electron_macos_notarization_tool(
    name = "notarize",
    signer = "@rcodesign_linux_x64//:rcodesign",
)
```

Run on the BB release client, outside cacheable artifact actions:

```sh
bazel run --config=bb-workflow //:notarize -- \
  --input signed-app.zip --output notarized-app.zip \
  --api-key-env NOTARY_API_KEY_FILE --max-wait-seconds 600
```

The environment variable holds the path to rcodesign's App Store Connect API
key JSON. Credentials stay outside rule attributes and action environments.
Input must already have valid Developer ID signatures, hardened runtime and
timestamps. Developer ID release signing remains open; assembly currently signs
ad hoc.

The client copies and validates the app ZIP, preserving executable modes, links
and empty directories. It removes a prior ticket from the snapshot and invokes
`notary-submit --wait --staple`. The pinned backend rejects non-accepted
submissions before stapling. Backend logs and inherited credentials are
suppressed. Failure, timeout, missing ticket or any other content/mode change
prevents output. A successful result creates a new ZIP atomically, preserving
existing or competing outputs. Generate updater metadata from this final ZIP.

Tests cover this protocol with a simulated service result, payload preservation,
failure isolation, final feed hashes and the real declared backend's invalid-
credential rejection. They do not contact Apple. Live Apple interoperability,
ticket trust and native Gatekeeper acceptance remain unverified. DMG/PKG
notarization and the Developer ID signing adapter remain separate gaps.
