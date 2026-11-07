# Hermetic builds

The bar is [hermeticbuild/nodejs](https://github.com/hermeticbuild/nodejs): declared
toolchains/sysroots and dependency closures, source/tool integrity pins, explicit
target versus execution platforms, deterministic product bytes.

Current enforcement:

- BB execution uses the digest-pinned amd64 `rbe-ubuntu22-04` image declared in
  `platforms/BUILD.bazel`, with external networking disabled. The network probe
  in `tests:hermetic_execution_test` runs under that execution configuration.
  OCI is selected explicitly with legacy `dockerNetwork=off`: BuildBuddy's
  current generic `network=off` conversion produces `none`, while the OCI
  network-enabled check compares against `off`. The verified TLS probe guards
  the actual behavior rather than trusting the property alone.
- Root and example workspaces enable strict action environments, disable default
  sandbox network access, and disable automatic C++/Apple/Swift host toolchains.
  LLVM toolchains and sysroots are declared Bazel inputs.
- Assembly, ASAR, update metadata and Linux payload actions use the pinned
  execution Python toolchain. Signing uses a digest-pinned execution-platform
  rcodesign archive. Target binaries never execute during packaging.
- Windows resource editing uses an explicit execution Node and pinned pure-JS
  `resedit`/`pe-library` closure. The example builds that Node from
  hermeticbuild/nodejs sources on BB. It is separate from Electron's embedded
  Node version; adding an execution tool does not change the target runtime.
- Runtime, source header and npm bootstrap archives carry integrity hashes.
  Lockfiles are checked in; CI rejects stale example module locks. Repository
  fetching is separate from network-disabled build actions. npm lifecycle scripts
  never run in the example adapter.
- Product archives use sorted paths, explicit modes/ownership, fixed timestamps
  and gzip headers without source paths. Release time is a declared update-feed
  input. Payload reproducibility tests change input mtimes before comparing bytes.
- Pinned `rules_pkg` writes the DEB container from declared payload/control inputs;
  it does not invoke host `dpkg`. Maintainer scripts are data until installation.

The official Electron runtime remains an explicit bootstrap dependency. It is
integrity-pinned but does not satisfy the separate source-built runtime goal.

Native GH hosts install/run/uninstall BB outputs. Their package-manager and GUI
setup belongs to execution testing, not product builds. The DEB test's local HTTP
feed and elevation adapter also live only in that native test path.

Performance follows this gate. Compare BB action profiles, cache reuse, peak
memory, transfer bytes and artifact sizes; preserve behavior and reproducibility
when changing implementations. Profiles may record clocks; product actions may not
read wall-clock time to choose their output bytes.

The BB cross-build workflow uploads `cross-build-profile.json.gz` with its
artifacts, including remote queue, process, download and cache-check events.
Use that trace and per-action BB resource stats for the performance baseline;
compare equivalent cold/warm builds before changing compression or action layout.
RBE uses top-level output downloads and compressed cache transport, matching
hermeticbuild/nodejs. Intermediate compiler outputs stay remote; required
top-level artifacts and runfiles remain available. This changes transport, not
product bytes. Subsequent profiles must establish the actual performance effect.
