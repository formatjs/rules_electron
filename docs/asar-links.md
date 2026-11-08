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

The example exercises linked main entry, packed directory reads, chained file
links and an unpacked native addon resolved through a file link. Hosted validation
is pending.
