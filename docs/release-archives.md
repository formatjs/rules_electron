# Release archives

`electron_archive` produces ZIP, tar, tar.gz, tar.xz or tar.bz2 from an `electron_app`. Compilation,
assembly and signing finish before archival. The action uses the declared Python
execution toolchain; it never runs target binaries or discovers host utilities.

```starlark
load("@rules_electron//electron:archive.bzl", "electron_archive")

electron_archive(
    name = "release",
    app = ":app",
    format = "zip",  # tar, tar.gz, tar.xz and tar.bz2 also supported
    compression_level = 6,
)
```

The output uses the selected format's extension. Each contains one top-level
directory: `executable_name` on Linux/Windows, `product_name.app` on macOS.
`root_name` overrides that directory; macOS names must end in `.app`. It does
not change the bundle's internal identity.

Compression levels range from 0 through 9; tar.bz2 requires 1 through 9. ZIP level
0 stores entries; tar.gz level 0 retains gzip framing without compression. XZ uses
the matching LZMA preset and CRC64. Plain tar ignores the compression level.
Compressors come from the declared Python toolchain. Level 1 favors packaging
time; level 9 favors size. Choose from measured costs for the consuming application.

Entries have stable ordering, normalized modes, fixed timestamps and no host
ownership metadata. Executables retain 0755, regular data 0644, directories 0755
and symlinks 0777. Relative symlinks stay links, including macOS framework chains.
Escaping, dangling and cyclic links, special files, duplicate ZIP paths and
file/directory collisions fail. macOS/Windows also reject case collisions.

macOS input ZIPs stream directly into the release archive without extracting to
disk. File bytes, embedded code signatures and link targets remain unchanged.
Archive reproducibility requires identical input bytes: a release signing service
may introduce its own timestamps. This rule does not sign or notarize artifacts.

Pass the final archive to `electron_update_feed` when generating update metadata.
Any later mutation requires new hashes and blockmaps. Archive generation alone
does not establish an installed-app updater lifecycle for that format.

BB tests cover tree and macOS ZIP inputs, changed paths/mtimes/order, executable
modes, signed-byte preservation, framework links and rejected archive graphs.
The desktop macOS smoke consumes this rule's ZIP, then verifies native launch,
code signatures and ASAR integrity on its matching host.
[33244d8 validation](https://github.com/formatjs/rules_electron/actions/runs/42352517657)
passed BB cross-builds and all four native host jobs. ZIP/tar.gz rule outputs also
passed the BB Linux fixture test. Native installed-app tar.gz update behavior
remains separate from archive generation.

The Linux example also builds `release_tar.tar.gz` on BB. Its native x64 smoke
checks archive ownership/timestamps, extracts with Python's data filter, then
runs the relocated app, native addon and ASAR checks. The
[0e7c8dd cross-build](https://formatjs.buildbuddy.io/invocation/53c2f516-85fa-4662-94d3-bde44a3646e8)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42522746234)
passed, including `TAR_RELEASE_SMOKE_OK` on Linux x64. Linux ARM64 remains
cross-built without a native host.

The [dfb15d7 assembly suite](https://formatjs.buildbuddy.io/invocation/ad07dce8-0c3b-472b-b498-a74fb3748cb8)
also passed real ZIP and all four tar rule outputs, changed source paths/mtimes,
compression boundaries, macOS signed bytes and framework links. This validates
the compressors in the declared Python toolchain; no host archive tools run.
