# Hermetic builds

The bar is [hermeticbuild/nodejs](https://github.com/hermeticbuild/nodejs): declared
toolchains/sysroots and dependency closures, source/tool integrity pins, explicit
target versus execution platforms, deterministic product bytes.

Compile source with native Bazel C/C++/Rust rules and declared generator actions.
Do not introduce CMake or `rules_foreign_cc` build wrappers.

Current enforcement:

- BB execution uses the digest-pinned amd64 `rbe-ubuntu22-04` image declared in
  `platforms/BUILD.bazel`, with external networking disabled. The network probe
  in `tests:hermetic_execution_test` runs under that execution configuration.
  Its `external`/`no-cache` tags force a fresh BB execution so cached success
  cannot hide an executor networking change.
  OCI is selected explicitly with legacy `dockerNetwork=off`: BuildBuddy's
  current generic `network=off` conversion produces `none`, while the OCI
  network-enabled check compares against `off`. The verified TLS probe guards
  the actual behavior rather than trusting the property alone.
- Root and example workspaces enable strict action environments, disable default
  sandbox network access, and disable automatic C++/Apple/Swift host toolchains.
  LLVM toolchains and sysroots are declared Bazel inputs.
- Assembly, ASAR, update metadata and Linux payload actions use the pinned
  execution Python toolchain. Root/example workspaces select its shell bootstrap,
  avoiding ambient Python during startup. A BB regression launches a Python tool
  with shell utilities available but no Python executable on PATH;
  [hosted tests passed](https://formatjs.buildbuddy.io/invocation/5d704086-1541-4c55-9701-a832adbf6d7d).
  POSIX shell bootstrap utilities remain part of the Linux execution
  platform. Signing declares the signer's full runfiles and uses a digest-pinned execution-platform
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
- NSIS uses a declared execution compiler and SDK tree, disables external
  configuration, and fixes its environment and file-date policy. Example v1
  installers compile twice with changed source paths/mtimes and require byte
  equality. Installer stubs/plugins execute only during native lifecycle tests.

Official Electron runtime archives are explicit, integrity-pinned inputs. This
repository packages those prebuilts; rebuilding Electron or its embedded
Chromium/Node is outside this dependency graph. Packaging tools, generators and
native addons continue to use native Bazel rules and declared toolchains.

The packaging cross-build action query includes forbidden build-wrapper
mnemonics alongside required app/DMG actions. The platform-input audit rejects
foreign-cc, CMake, Meson, Ninja, Make and direct GN actions. This mnemonic check
does not inspect arbitrary script contents; declared tool closures and reviewed
native rules remain part of the hermeticity contract.
