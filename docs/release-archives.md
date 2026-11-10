# Release archives

`electron_archive` produces ZIP, tar, tar.gz, tar.xz, tar.bz2, tar.lz, tar.7z or 7z from an `electron_app`. Compilation,
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

`tar.lz` requires a declared `lzip` execution tool. The repository provides
`@rules_electron//third_party:lzip`, built from checksum-pinned GNU lzip 1.25
with native `cc_binary`; configure, Make and CMake never run. Levels 0 through 9
select lzip's corresponding modes; level 0 still compresses. `tar.7z` requires
the same declared `sevenzip` tool as `7z`, with level 0 selecting Copy.
Both formats wrap the deterministic PAX tar in one compressed member, retaining
signed bytes, relative links, executable modes and tracked empty directories.

```starlark
electron_archive(
    name = "release_lzip",
    app = ":app",
    format = "tar.lz",
    lzip = "@rules_electron//third_party:lzip",
)
```

BB interoperability checks cover native lzip compression with independent
LZMA/header/trailer decoding, declared 7zip extraction, relocation/mtime
reproducibility, Unicode paths and macOS signature bytes. The
[1772ee8 suite](https://formatjs.buildbuddy.io/invocation/1951142b-2935-4178-8b33-0457d06b54a8)
passed those checks and the public rules' actual app-fixture outputs. Desktop
`release_lzip` and `release_tar7z` targets now enter both Linux cross-builds;
Linux x64 smoke decodes each and launches the packaged Electron app. The
[8ec226b suite](https://formatjs.buildbuddy.io/invocation/db320be9-7576-4458-a8e4-1df2fac8973a),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/769e347f-4145-49e0-8e55-2b9734638a2e)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42744591879)
passed. Linux x64 executed the BB-built GNU lzip decoder, then launched Electron
from both extracted formats. Linux ARM64 remains build-only.
ZIP/tar compressors come from the declared Python toolchain. Level 1 favors packaging
time; level 9 favors size. Choose from measured costs for the consuming application.

Entries have stable ordering, normalized modes, fixed timestamps and no host
ownership metadata. Executables retain 0755, regular data 0644, directories 0755
and symlinks 0777. Relative symlinks stay links, including macOS framework chains.
Escaping, dangling and cyclic links, special files, duplicate ZIP paths and
file/directory collisions fail. macOS/Windows also reject case collisions.

ZIP/tar outputs stream macOS input ZIPs without extracting to disk. File bytes, embedded code signatures and link targets remain unchanged.
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

For `format = "7z"`, supply `sevenzip` as an execution-platform executable label.
The example pins its standalone Linux 7zip bootstrap tool by SHA-256; consumers
may provide a Bazel source-built tool. No execution-host search or package manager
runs during archive creation.

```starlark
electron_archive(
    name = "release_7z",
    app = ":app",
    format = "7z",
    sevenzip = ":execution_7zip",
    compression_level = 1,
)
```

7z stages the validated inventory privately, then preserves relative symlinks,
empty directories, normalized Unix modes and file bytes. Time fields are omitted.
Compression uses independent LZMA2 streams, a 1 MiB dictionary and two fixed
threads; level 0 selects Copy. Input paths and mtimes never enter product bytes.

[BB tests](https://formatjs.buildbuddy.io/invocation/f1b88d88-6931-46ac-b4bb-240edab428e6)
passed levels 0/1/9, real extraction, changed roots/mtimes, executable modes,
Unicode names, directory/file links and macOS ZIP seal-byte preservation.
[BB cross-build matrix](https://formatjs.buildbuddy.io/invocation/ce7223d5-b1b1-4b20-b116-32613f2579ae)
passed, with 7z outputs for both Linux CPUs. The native Linux x64
[7z extraction/launch gate](https://github.com/formatjs/rules_electron/actions/runs/42543234956/job/128922799241)
passed with independent p7zip (`SEVENZIP_RELEASE_SMOKE_OK`). The later RPM
installed-update gate failed on the older client's dnf detector; this link
establishes archive extraction/launch coverage, not a green combined job.
Archive creation remains on BB. Installed-app updates remain a separate contract.
