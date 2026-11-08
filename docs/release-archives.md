# Release archives

`electron_archive` produces a ZIP or tar.gz from an `electron_app`. Compilation,
assembly and signing finish before archival. The action uses the declared Python
execution toolchain; it never runs target binaries or discovers host utilities.

```starlark
load("@rules_electron//electron:archive.bzl", "electron_archive")

electron_archive(
    name = "release",
    app = ":app",
    format = "zip",  # or tar.gz
    compression_level = 6,
)
```

The output is `release.zip` or `release.tar.gz`. Both contain one top-level
directory: `executable_name` on Linux/Windows, `product_name.app` on macOS.
`root_name` overrides that directory; macOS names must end in `.app`. It does
not change the bundle's internal identity.

Compression levels range from 0 through 9. ZIP level 0 stores entries; tar.gz
level 0 retains gzip framing without compression. Level 1 favors packaging time;
level 9 favors size. Choose from measured costs for the consuming application.

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
runs the relocated app, native addon and ASAR checks. Validation is pending.
