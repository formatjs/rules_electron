# ASAR integrity

`electron_app(asar = True)` writes per-file SHA-256 and block hashes. On macOS it
also writes the raw JSON header's SHA-256 to
`Info.plist:ElectronAsarIntegrity:Resources/app.asar`, using
[Electron's embedded integrity contract](https://www.electronjs.org/docs/latest/tutorial/asar-integrity).
The digest excludes the ASAR pickle framing and padding. It is derived during
archive creation; packaging does not reread the full archive to calculate it.

Enable runtime enforcement explicitly:

```starlark
fuses = {
    "enableEmbeddedAsarIntegrityValidation": "on",
    "onlyLoadAppFromAsar": "on",
    "runAsNode": "off",
    "enableNodeOptionsEnvironmentVariable": "off",
    "enableNodeCliInspectArguments": "off",
},
```

On macOS, fuses live in `Electron Framework.framework/Electron Framework`.
Assembly edits that binary and the app plist before execution-platform rcodesign
seals the bundle. Current mutation requires one fuse sentinel, matching the
single-architecture runtime targets. Unavailable/removed fuses fail packaging.
Unspecified fuses retain their runtime defaults.

Embedded validation requires `asar = True`. Windows additionally requires a
declared [resource tool](windows-resources.md); it writes the digest as an
`INTEGRITY` / `ELECTRONASAR` PE resource before fuse mutation and final signing.
Linux Electron does not implement this enforcement.
Additional archives use `electron_asar` and `electron_app.extra_asars`:

```starlark
load("@rules_electron//electron:asar.bzl", "electron_asar")

electron_asar(
    name = "shared",
    srcs = {
        "shared.cjs": "index.cjs",
        ":native_addon": "addon.node",
    },
    unpacked = ["addon.node"],
)

# On electron_app:
extra_asars = {":shared": "plugins/shared.asar"},
```

The standalone rule accepts file/tree mappings. It produces an archive, unpacked
sidecar tree and raw-header digest. Default files contain the archive;
`unpacked` and `header_hash` output groups expose the other artifacts.
`extra_asars` consumes these declared outputs, checks the digest, copies the
archive/sidecar and embeds the additional header hash in the macOS plist or Windows PE
resource. Windows embedding requires its declared resource tool. Linux retains
the archive's per-file hashes but has no embedded-header enforcement.
Use `extra_asars` for this contract; a generic `extra_resources` mapping supplies
only the mapped artifact.

The native example loads a module and unpacked Node-API addon/data from an
additional archive. Its corruption checks cover both archives' headers and
packed payloads. Hosted validation for this addition is pending.

Unpacked files and extra resources are not protected by the ASAR header's
packed-file validation; release signing and installation permissions remain
separate requirements.

The desktop example enables these fuses. Native macOS smoke first verifies the
signature and launches the sandboxed app with hostile Node environment flags.
It then changes one valid header hash byte and, separately, one payload version
byte. Each launch must terminate with Electron's integrity failure diagnostic.
After restoring bytes, Apple's deep/strict signature verification must pass.
The [native macOS run](https://github.com/formatjs/rules_electron/actions/runs/42345084890/job/128321847848)
passed all three launches and restored signature verification against BB output.
These checks use the pinned bootstrap Electron runtime; source-runtime launch
remains a separate goal.

Windows smoke uses native resource/version APIs to check the embedded digest and
product/version strings, then runs the same header/payload corruption checks on
both compiler variants per available Windows CPU host. Hosted results establish
runtime enforcement; analysis alone does not.
The [Windows x64/ARM64 run](https://github.com/formatjs/rules_electron/actions/runs/42347096977)
passed metadata inspection, normal launch and both corruption checks for all four
Windows variants.
