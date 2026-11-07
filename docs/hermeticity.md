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
- NSIS uses a declared execution compiler and SDK tree, disables external
  configuration, and fixes its environment and file-date policy. Example v1
  installers compile twice with changed source paths/mtimes and require byte
  equality. Installer stubs/plugins execute only during native lifecycle tests.

The official Electron runtime remains an explicit bootstrap dependency. It is
integrity-pinned but does not satisfy the separate source-built runtime goal.

The [Electron source overlay at 8148c8f](https://github.com/formatjs/electron/commit/8148c8f)
now uses the same pinned offline OCI execution settings, disables C++/Apple/Swift
host toolchain discovery and enables compressed remote-cache transport. Its
development and BCR consumer workflows run fresh remote TLS-denial probes before
compilation. All three hosted checks passed: [source components](https://formatjs.buildbuddy.io/invocation/6e7cffa3-fb36-4227-93f1-b0608a0f8e98),
[cross-compile](https://formatjs.buildbuddy.io/invocation/0f7d2e3f-c599-4a3a-b79d-3bb4ba3b09fe)
and [BCR consumer](https://formatjs.buildbuddy.io/invocation/f409e74a-0e0b-4129-818e-85a44a15c9cb).
These validate existing source components, not a complete Electron executable.

Temporal now uses `hermeticbuild/rules_rs` with a pinned nightly SDK. Its captured
57-target closure projects individual files from the matching Chromium archive;
Cargo does not resolve or download dependencies. Original build scripts and
bindgen use declared inputs. Rust keeps captured allocator settings, backed by
real PartitionAlloc FFI. Calendar/DST tests disable ambient ICU file loading.
[Component](https://formatjs.buildbuddy.io/invocation/df7fed7a-c08b-46f4-be2d-dcb6467631df)
and [consumer](https://formatjs.buildbuddy.io/invocation/75b513b8-c73b-4fb4-a035-0122c0ed452d)
checks passed with the fresh network-denial gate.

Perfetto's complete captured closure now uses original patched sources, matching
source-built Protobuf 32 tools and exact JsonCpp DEPS bytes. Its 68 generators
use declared execution tools, isolated Python, empty child `PATH` and explicit
environments. Every generator requires byte equality across different staging
paths and input mtimes. The [consumer](https://formatjs.buildbuddy.io/invocation/781d378c-801e-46f9-a1a9-45bfd2007deb)
passed real tracing/decoding and captured JsonCpp failure behavior; the
[component workflow](https://formatjs.buildbuddy.io/invocation/3072778c-6b5f-4d26-ad16-aa721e45c7f4)
also passed. These native profiles remain Linux AMD64.

The complete patched V8 engine now links source-built dependencies and generated
snapshots. Original `mksnapshot` disables host CPU probing; captured target flags,
predictable mode and fixed seed remain explicit. Snapshot/inspector generators
verify output bytes across changed paths/mtimes. Wasm's direct standard-header
fix applies to an owned projection file and records its provenance.
[4516ed7 consumer](https://formatjs.buildbuddy.io/invocation/ec9a0537-868a-4182-9ec0-ded5e613b4ef)
passed JS, Wasm, Intl, Temporal and inspector execution with generated startup
data. This validates the Linux AMD64 V8 engine; full Electron still needs linking.

Chromium base now builds its captured 425-unit root and support libraries with
pinned native GLib, matching ICU/BoringSSL headers and the original Rust CXX
bridges. The combined Temporal/base closure uses 85 Rust targets from 65 vendored
packages. Fixed build dates and declared version files replace ambient clock/git
inputs. CXX configuration comes from the pinned target Rust compiler; its native
compiler runs in execution configuration. Original Python generators retain
path/mtime byte checks. [4746f81 consumer](https://formatjs.buildbuddy.io/invocation/37a9576f-eea3-4c65-8205-6dabc9b3426e)
passed Rust JSON parsing, invalid-input rejection, serialization, Base64 and
native GLib task/idle dispatch after the fresh network-denial gate. Base remains
Linux AMD64; full source-built Electron still needs linking.

Patched libnode now uses its original Chromium inspector generators and matching
Brotli/Zstd sources. Actual PDL inputs and imported `Runtime.h` are declared;
generators retain path/mtime byte checks. GNU `-latomic` maps to source-built LLVM
compiler-rt, verified through generic 24-byte atomics. Native shared-addon bytes
materialize in a regular `.node` file through pinned Python: Node resolves
symlinks before selecting its loader. The lifecycle compatibility patch applies
to an owned source copy and records provenance. [40b2baf components](https://formatjs.buildbuddy.io/invocation/db60fdd2-5715-468b-aad5-05013a89fa46)
and [consumer](https://formatjs.buildbuddy.io/invocation/257b7fb2-b546-4a98-8b6a-6e1cfb45fa73)
passed actual Node startup, module APIs, native-addon loading and shutdown, after
the fresh network-denial gate. This validates Linux AMD64 libnode; full Electron
and other complete source profiles remain pending.

Gin, Base i18n and CED reuse pinned V8/Base/ICU dependencies. Original buildflag
generators retain isolated Python, explicit inputs and path/mtime byte checks.
ICU and generated snapshot data enter through declared file APIs, without host
asset discovery. [5bca689 consumer](https://formatjs.buildbuddy.io/invocation/93435deb-d75a-4138-a291-8f1c2c115443)
passed actual Unicode, native callback, sandboxed allocation and shutdown checks
after the fresh network-denial gate. This full profile remains Linux AMD64.

IPCz projects all captured source sets from the same Chromium archive, preserving
original flags and shared Base/Abseil inputs. Its synchronous reference driver
is test-only. [c961819 consumer](https://formatjs.buildbuddy.io/invocation/3afbac9c-cb0e-4445-a246-0b6d499ffcde)
passed real portal transfer and binary messaging after the fresh network-denial
gate; no separate IPCz source revision or standalone shim enters the build.

Mojo/networking now declares source/public headers and included compiler inputs,
including SQLite's original shim/amalgamation. Matching source-built protoc,
root-store and HSTS tools run in execution configuration. Native NSS/NSPR build
rules come from pinned `formatjs/chromium`; CMake and `rules_foreign_cc` remain
absent from the resolved module and action graphs. Owned GRIT adaptations remove
temporary paths from resource metadata without changing resource bytes.

NSS integrity metadata uses a public build key and RFC 6979 nonces with original
NSS arithmetic. Actions compare bytes across paths/mtimes; published nonce
vectors pass. The [122f977 consumer](https://formatjs.buildbuddy.io/invocation/376c61c9-c0a3-471b-b9a7-2d07d498f510)
passed original NSS verification of generated/relocated checksums and rejection
of changed module/signature bytes after the fresh network-denial gate. HSTS
checks both sides of its original 70-day expiry with a scoped test clock.
Production clocks and runtime randomness remain unchanged. This validates the
Linux AMD64 source closure; full Electron still needs linking.

Typed Mojo generators retain original parser inputs, response files, typemaps
and literal GN metadata. All 29 actions compare output bytes across changed
paths/mtimes with empty child `PATH`. The 345 shared Mojo headers retain their
existing file identity.
[8261fc4 components](https://formatjs.buildbuddy.io/invocation/7616e6df-a464-4d31-9870-8675906e3d6c)
and independent consumer checks passed; runtime coverage includes real native
child-process IPC and generated typed dispatch. Full Electron remains unfinished.

FreeType/HarfBuzz archives use exact DEPS commits with SHA-256 pins. All 959
external source inputs match their original checkout bytes; changing Gitiles
archive bytes triggered checksum rejection during setup, so stable GitHub
mirrors supply these archives. Native font, PNG and XML probes use declared ICU
data and font bytes, without host font discovery.
[854f6a7 consumer](https://formatjs.buildbuddy.io/invocation/be89e67e-3a77-4364-917e-c8cd913427de)
passed the Linux AMD64 runtime checks.

Fontconfig uses its exact DEPS commit and checksum-pinned archive, preserving
`ENABLE_FONTATIONS`. Two native bindgen boundaries retain original C-header
filters and configuration; capture records and verifies the original bindgen
configuration source hash. Existing Rust allocator/prelude/toolchains and crate
records stay shared. The [6652729 consumer](https://formatjs.buildbuddy.io/invocation/d79263f3-c960-4981-acad-338cd9b5d328)
passed native fontations scanning/matching with explicit empty configuration,
declared font bytes and invalid-input rejection. New closure action audit
found no CMake or foreign-cc actions. Full source profiles remain Linux AMD64.

JPEG and NASM retain exact Chromium fork commits through pinned Git fetches;
WebP/Wuffs archives retain exact DEPS commits and checksums. Original NASM
2.17rc0 builds on the execution platform; no host executable lookup participates.
All 27 original SIMD runs retain `--reproducible`, declared inputs and changed
path/mtime object-byte equality.
[a4c1c6a consumer](https://formatjs.buildbuddy.io/invocation/3539d526-2758-4b59-8fc0-06b5fc20d11f)
passed native JPEG/WebP/GIF runtime probes. The new closure action audit found
no CMake or foreign-cc actions.

Skia/Dawn/Vulkan headers use exact DEPS revisions and SHA-256 archive pins.
All 15 original generators retain changed-path/mtime byte checks. Dawn expected
outputs derive from captured extractor declarations, with source provenance
recorded; original validation still runs. A declared pinned revision supplies
`DAWN_VERSION`, removing checkout-hook/Git dependence from actions. Native CXX
reuses the pinned compiler configuration and executable. Shared PartitionAlloc
and Wuffs providers export original headers/include paths without replacement
implementations. [3d7a5d1 consumer](https://formatjs.buildbuddy.io/invocation/eb13ad3b-8467-451d-8ff5-41aaafca7a66)
passed CPU raster/SkSL and Rust PNG/fontations probes; hardware GPU contexts
remain untested. The source action audit found no CMake or foreign-cc actions.

Native gfx preserves exact DEPS Git revisions for libdrm/libsync and uses
Electron-patched Crashpad from Chromium. All 34 original Python generators keep
changed-path/mtime byte checks; four literal GN metadata targets retain captured
bytes. Original cc export headers and Crashpad assembly includes are declared.
Shared-profile capture reproduces validated Skia metadata byte-for-byte.
[8f46f43 consumer](https://formatjs.buildbuddy.io/invocation/e3112348-39f6-47a5-8001-f72d63c0f457)
passed real gfx runtime checks. No CMake/foreign-cc actions matched the gfx action
audit. Full source profiles remain Linux AMD64; GPU/device and Crashpad process
execution remain untested.

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
