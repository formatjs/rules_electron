# AppImage

Full AppImage packaging and updater lifecycle remain open.

`//electron/tools:mksquashfs` and `//electron/tools:unsquashfs` build pinned
SquashFS 4.7.5 sources with native Bazel C/C++ rules. gzip and zstd use native
BCR libraries. No Make, Meson, CMake, host package discovery or target execution
participates in these builds.

The BB tool test packs and extracts real files with both codecs, including
Unicode names, executable modes, empty directories and directory links. It
compares filesystem bytes across changed input paths/mtimes, with fixed
ownership and timestamps. Validation is pending.

The remaining stages are a source-built type-2 runtime, declared AppDir assembly,
embedded updater maps, cross-builds for both Linux CPUs and a native Linux x64
launch/update lifecycle. No emulation substitutes for native smoke.
