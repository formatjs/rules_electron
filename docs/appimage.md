# AppImage

Full AppImage packaging and updater lifecycle remain open.

`//electron/tools:mksquashfs` and `//electron/tools:unsquashfs` build pinned
SquashFS 4.7.5 sources with native Bazel C/C++ rules. gzip and zstd use native
BCR libraries. No Make, Meson, CMake, host package discovery or target execution
participates in these builds.

The BB tool test packs and extracts real files with both codecs, including
Unicode names, executable modes, empty directories and directory links. It
compares filesystem bytes across changed input paths/mtimes, with fixed
ownership and timestamps. [BB tests](https://formatjs.buildbuddy.io/invocation/3accdcef-56fa-44a3-8f42-cb16a65afa99)
and [cross-builds](https://formatjs.buildbuddy.io/invocation/e8b9f780-b107-43f7-b7d4-2358e9e925fa)
passed at `a0d5e62`. The tool test runs on Linux x64; AppImage target runtime
cross-builds remain pending.

The remaining stages are a source-built type-2 runtime, declared AppDir assembly,
embedded updater maps, cross-builds for both Linux CPUs and a native Linux x64
launch/update lifecycle. No emulation substitutes for native smoke.
