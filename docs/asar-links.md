# ASAR links

Use `electron_asar.symlinks` or `electron_app.asar_symlinks` to map link paths to
archive-root-relative targets. An empty target denotes the archive root:

```starlark
asar_symlinks = {
    "entry.cjs": "main.cjs",
    "package-assets": "assets",
},
```

Links become ASAR header entries, with no filesystem symlinks or duplicate packed
payload. Assembly validates normalized paths, missing targets, file/directory
collisions and cycles before writing the archive. Link chains and targets through
directory links resolve to canonical archive paths. File links can select the app
entry point. Mark actual files, rather than links, in `asar_unpacked`/`unpacked`.

The contract follows the pinned Electron ASAR reader. Packed file/directory reads
and module resolution use its virtual namespace. Direct filesystem operations
through aliases to unpacked files still depend on the runtime's sidecar path
handling; those aliases are not materialized in the sidecar. Input-tree filesystem
symlinks remain a separate mapping concern.

The source overlay's [canonical resolver patch](https://github.com/formatjs/electron/commit/0a54b87346be709f43bb70a8b80209def644ce2c)
addresses direct unpacked aliases, chained directory/file links, root aliases and
canonical extraction cache keys. Its focused resolver test passed in the
[BB consumer preflight](https://formatjs.buildbuddy.io/invocation/0133feee-c4e4-4e99-8560-c5cca00d3180).
The [6c5ad31 consumer preflight](https://formatjs.buildbuddy.io/invocation/2ad91d1f-91e3-4950-a76a-65a631b812cd)
also passed `asar_reader_test`, compiling the real `Archive`, `asar_util` and
temporary-file implementation. It checks unpacked alias reads/writes, shared
packed-file extraction identity, final-link stats, directory enumeration and
cycle rejection. Full-runtime Node filesystem smoke remains unverified.
The bootstrap runtime used by native examples
does not contain this patch; direct unpacked alias support remains a migration
gate until source-runtime smoke passes.

The example exercises linked main entry, packed directory reads, chained file
links and an unpacked native addon resolved through a file link.

[BB tests](https://formatjs.buildbuddy.io/invocation/c8b7456c-a727-4595-bbb9-103bb30ab4a3),
[seven cross-build variants](https://formatjs.buildbuddy.io/invocation/b1b6006e-75ae-4641-9cd5-db12fc57f84d)
and [native smoke](https://github.com/formatjs/rules_electron/actions/runs/42461286829)
passed. Native coverage includes Linux x64, macOS ARM64 and Windows x64/ARM64
with GNU LLVM/MSVC, plus existing installer/update and integrity checks.
