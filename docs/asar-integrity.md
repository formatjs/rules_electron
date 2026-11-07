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

Embedded validation currently requires macOS and `asar = True`. Windows resource
embedding remains pending; Linux Electron does not implement this enforcement.
Additional ASAR files outside `app.asar` have no generated embedded digest.
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
