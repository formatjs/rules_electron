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

Native display reuses matching Chromium/gfx sources and all existing dependency
identities. Its 21 original generators retain changed-path/mtime byte checks.
Compound Mojo `EnableIf` AST nodes retain parser filenames in serialized modules;
the shared source projection now passes source-relative diagnostic filenames,
preserving feature evaluation and wire semantics. Generator children use `-s -P`
with an explicit clean environment, honoring `PYTHONHASHSEED=0` while disabling
user site/current-directory imports. The [81686a0 consumer](https://formatjs.buildbuddy.io/invocation/8c32e657-744a-4257-b51d-53ba5f139a24)
passed native display and existing source runtime checks. Action analysis found
no CMake/foreign-cc actions. Display tests use explicit model values without host
monitor discovery; physical-device execution remains separate coverage.

Native events preserve all 76 original generator actions, declared execution
protoc/plugins and original protocol-copy bytes. Matching Snappy uses its exact
DEPS commit. Chromium's vendored X11 keysym header and three textually included
keyboard C implementations remain original declared inputs.

The native XCB projection reuses checksum-pinned BCR libxcb/xcb-proto sources,
replacing ambient shell copies/moves with declared Python actions and changed
path/mtime byte checks. Linux abstract sockets remain enabled, as in the Chromium
reference. Native libxau/xkbcommon use their BCR source rules. Action analysis
found no CMake or foreign-cc actions. [076dc2e consumer](https://formatjs.buildbuddy.io/invocation/3b776ef1-7a74-44e3-a5b5-474214e5a32a)
passed real input/XKB/X11/XCB/compression probes. Keyboard data is explicit;
default includes/environment names are disabled. The X11 wire probe uses public
interfaces and needs no server. Physical X11/device execution remains untested.

Native GH hosts install/run/uninstall BB outputs. Their package-manager and GUI
setup belongs to execution testing, not product builds. The DEB test's local HTTP
feed and elevation adapter also live only in that native test path.

The native UI/WebUI closure retains original TypeScript, ESLint, minification,
GRIT and locale generation. Chromium DEPS pins execution Node 22.11.0 and the
prepatched npm archive; no package install hooks or host Node discovery run.
Directory tools receive declared predecessor outputs, source declarations and
static resource assets. Generator byte checks remain enabled. Native probes
reload relocated English/French packs, compare packed module bytes, exercise
color mixing and execute the actual generated JavaScript.
[2b46400 components](https://formatjs.buildbuddy.io/invocation/589e4e60-43b7-410f-b0c4-afd40ab9c125)
and [consumer](https://formatjs.buildbuddy.io/invocation/c1ddb72f-d5fb-446f-8cb4-ea7e8e39da31)
passed. The UI action audit found no CMake/foreign-cc actions. Complete source
profiles remain Linux AMD64; full Electron still does not link.

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

## Ozone/GL source boundary

The upstream source aggregate builds 2,147 captured Ozone/GL units with native
Bazel rules and original generators. Fifteen source repositories retain exact
Chromium/Dawn DEPS commits. Native generator data is declared beside its original
executable in the execution configuration. SDK/platform header providers forward
compilation context; Rust FFI crates depend directly on their native C++ owners.
The action audit found no CMake/foreign-cc actions.

Desktop ABI data remains 53 files from 49 checksum-pinned Debian packages matching
the Chromium SDK. Native shared GLib/GObject/GModule/GIO and zlib take priority over
their five SDK counterparts, keeping initialization state in one shared owner.
The source platform selects glibc 2.31 to match the SDK. These SDK files are not
source-built library claims.

C/assembly members of shared targets link eagerly like C++ members. Previously,
lazy archive groups discarded every Vulkan loader export. The direct export test
[failed before the fix](https://formatjs.buildbuddy.io/invocation/40db6f85-9e36-463c-84c0-88d1b3550b28).
The [fixed probe](https://formatjs.buildbuddy.io/invocation/e6945d5b-4ab5-42fe-929a-f983b435fc58)
checks real loader dispatch, selects source SwiftShader explicitly, renders a 2×2
framebuffer and verifies every pixel byte. Temporary crash probes are removed.
The clean [e677b62 components](https://formatjs.buildbuddy.io/invocation/7056db57-2403-44a5-ac43-048b82fa95ec),
[consumer](https://formatjs.buildbuddy.io/invocation/0109ff8b-c8e5-4faf-9cda-c333de0a4be3)
and [cross probes](https://formatjs.buildbuddy.io/invocation/eb37a769-f425-4ba9-9c64-5f77a864c1a2)
also passed.

[consumer](https://formatjs.buildbuddy.io/invocation/44781263-425a-4713-a6e2-288114a29449)
and [cross probes](https://formatjs.buildbuddy.io/invocation/2a544517-a493-4bd2-9e08-ac3beb1bee52)
passed. Component profiles remain Linux AMD64; full Electron and other source
profiles remain unfinished.

## GPU command-buffer source boundary

The upstream Linux AMD64 profile now captures 2,639 native units across 409
library/group/runtime targets, including GLES2 client/service command buffers,
Viz common and GPU IPC client/host/service. Sixteen exact source pins include
Chromium's libyuv revision. The original Dawn checkout hook uses its supported
pinned revision/time environment; no Git or clock lookup runs inside that action.
Quoted sibling headers retain their original relative layout across profile
boundaries instead of being redirected into another source repository.

The [5cb43b3 aggregate](https://formatjs.buildbuddy.io/invocation/db1109b0-980c-44fe-99f1-153b9efa8946)
and [SwiftShader pixel probe](https://formatjs.buildbuddy.io/invocation/e88612d6-5558-453f-8b13-ee2aa123e107)
passed on BB. [9a26e4a components](https://formatjs.buildbuddy.io/invocation/85548eee-1919-463f-b3bc-faff67712494),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/7fe6e314-f4e1-48e2-a742-0f55ecf58e30)
and [cross probes](https://formatjs.buildbuddy.io/invocation/2c7580d3-ff97-41a2-a821-cdd4ce646ecb)
also passed. The complete native suite exercises real command transfer, malformed
ranges/handles, libyuv conversion bytes, GPU preference Mojo serialization, shader
cache protobufs and Viz plane sizing. Its launcher declares the pinned desktop
runtime closure alongside source-built shared owners. Full Electron remains unfinished.

## Symphonia Rust/CXX boundary

The source overlay now captures Chromium's Symphonia FLAC bridge: ten additional
Rust targets and nine vendor packages. Existing 107 Rust target records retain
their configuration. Original CXX generation uses source-built cxxbridge, declared
Rust target configuration and original Python helpers, with byte reproducibility
checks across source paths and mtimes. Generated headers forward compilation
context separately from native link ownership. No foreign build wrapper is used.

[bdd6d7e components](https://formatjs.buildbuddy.io/invocation/86cc1e18-00a5-4033-96eb-cb6f81f7e986),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/b5e0d4f7-7a0e-43a7-9cc1-e93a4dfe85de)
and [cross probes](https://formatjs.buildbuddy.io/invocation/86f8eb41-b3fe-4e20-8731-d765a70eced7)
passed. The native test compares decoded samples through the original CXX/Rust
bridge against a WAV reference whose PCM checksum matches the pinned FLAC fixture.
It also checks packet errors, recovery and rejected initialization. Structured BB
results explicitly report Symphonia, GPU transport and SwiftShader as PASSED.
This source dependency remains Linux AMD64; full media, compositor and Electron
integration remain unfinished.

## Media codecs and audio ABI

The Electron platform profile now imports the original full media closure:
1,529 additional C/C++ units and 156 NASM object actions. Combined coverage is
4,324 source/object units, 493 library/group/runtime targets, 203 generator
targets with 353 runs, and 27 exact source pins. FFmpeg reuses Electron's patched
repository. Original NASM, codec configuration and stub generators use declared
inputs/tools; source capture includes nested textual C inputs and selected
module header namespaces. Compiler macro expressions retain their original
single-argument spelling. No CMake or foreign-cc actions matched the graph audit.

[755d607 components](https://formatjs.buildbuddy.io/invocation/459c32ae-27ea-4ac6-bf40-b3908f40ca8d),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/65b0f31c-7d09-4a0b-93fa-36ad204cd4e2)
and [cross probes](https://formatjs.buildbuddy.io/invocation/bd1165c5-db04-43b3-963e-6359254e6449)
passed. Structured source-suite results report media runtime, ALSA ABI, Symphonia,
GPU transport and SwiftShader as PASSED. FFmpeg decoding matches every sample
of an independent WAV reference; tests also check the original Chrome AAC/H264
registry, Chromium audio parameters and ALSA allocation/version APIs.

The SDK/runtime closure contains 54 libraries from 50 checksum-pinned Debian
packages. The stripped ALSA link interface and real runtime have identical
symbol tables, symbol versions and build identity; executable sections are
present only in the runtime. Pulse headers support original lazy-load stubs;
server/device integration remains untested.

The source aggregate took 89.022 seconds with 801 tracked remote actions,
1,409.599 CPU seconds, 740,192,256 bytes maximum action peak memory,
940,670,748 input bytes and 57,764,434 output bytes. The subsequent complete
source suite took 39.912 seconds with zero remote actions. These are incremental
CI observations, not cold-build benchmarks. Full source profiles remain Linux
AMD64; compositor and full Electron integration remain unfinished.

## Compositor closure

The platform profile includes the original compositor closure: 2,017 additional
C/C++ units, Electron-patched WebRTC, pinned federated-compute/SRTP sources and
original metrics, field-trial, permissions-policy and GRIT generators. Combined
coverage is 6,341 source/object units, 1,490 library/group/runtime targets,
525 generator targets with 675 runs and 30 exact source pins. Existing 493 library
and 203 generator records remain unchanged. File-valued generator options declare
their inputs; field-trial generation uses its supported `--year=2025` option.
SDK PipeWire/SPA headers and five real X11 runtime packages are declared. Runtime
coverage is 59 libraries from 55 checksum-pinned packages, with SDK/runtime ABI
metadata checked. The graph audit found no CMake or foreign-cc actions.

[4a2bf7d components](https://formatjs.buildbuddy.io/invocation/76fcec92-d070-4111-bb69-9409ad3645a0),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/e094d365-9ce7-4b46-a66b-d7eb2df6f6ef)
and [cross probes](https://formatjs.buildbuddy.io/invocation/462db483-9fb6-4093-9889-cecbb0577540)
passed. Structured tests report compositor, media runtime, ALSA ABI, Symphonia,
GPU transport and SwiftShader as PASSED. The compositor probe checks layer
ownership/reparenting, then every raster pixel after clipping, translation and
alpha blending. Full source coverage remains Linux AMD64; full Electron is
unfinished.

The warm aggregate took 164.160 seconds and the following source suite 100.692
seconds, each with zero tracked remote actions. BCR source tests took 301.185
seconds with two tracked actions, 4.065 CPU seconds, 356,081,664 bytes maximum
action peak memory, 437,200,229 input bytes and 9,228,165 output bytes. These are
incremental observations. Warm orchestration/cache/download overhead needs
profiling; these figures do not establish cold-build performance.

## Blink Rust prerequisites

The source overlay now captures Blink's original font-format detector and
Rust/C++/Rust crash path. Two new Rust targets reuse all 89 vendor package
inventories; the existing 117 Rust records, Symphonia bridge and V8 provider
metadata remain unchanged. Original CXX generation uses declared source-built
cxxbridge, rustc configuration and Python helpers. Header-only compilation
providers keep native link ownership separate; the crash callback retains its
original C++ source, flags and source-set link behavior.

[d158dbb components](https://formatjs.buildbuddy.io/invocation/16dbafe5-cc1e-40b8-961b-0ae8fae9d3bd),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/74320089-9454-4c96-9c7e-23d9a7140085)
and [cross probes](https://formatjs.buildbuddy.io/invocation/136d9125-d6f6-4c63-a668-8e89365933b6)
passed. Structured results report both new probes as PASSED. Seven pinned SFNT
fixtures exercise format detection and malformed/truncated input. The isolated
crash child must reach the original Rust panic and terminate with SIGABRT;
core dumps are disabled. This checks the language boundary, not crash reporting.

The full dependency action audit found zero CMake/foreign-cc actions. Its positive
control found 20,791 CppCompile actions across platform and bridge dependencies.
Both queries traversed `deps(...)`; local analysis executed zero build actions.
Full source profiles remain Linux AMD64. Blink and full Electron are unfinished.

## CrabbyAVIF source integration

The original Chromium DEPS pin supplies CrabbyAVIF source. Three new Rust
targets bring the captured graph to 122; the existing 119 records and 89 vendor
package inventories stay unchanged. Native Bazel bindgen actions generate the
original dav1d/libyuv binding filenames with their captured public definitions.
Native codec targets retain link ownership. No Cargo build scripts or CMake
wrappers replace this graph.

The decode probe uses Chromium's parse/frame API and decoder-owned image.
The pinned convenience ReadMemory API shallow-copies metadata pointers; freeing
that copied image is unsafe. The probe compares every RGB byte against the
upstream lossless PNG fixture, then exercises separately owned RGB/YUV buffers.
[4cc896e components](https://formatjs.buildbuddy.io/invocation/de7eaeb8-6cfd-4177-ab99-5abd15832f99),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/bf52cd98-63f3-4b1a-b28b-4bb58dc007ad)
and [cross probes](https://formatjs.buildbuddy.io/invocation/15a831a3-e85e-45c3-a4fd-be8090bb46e8)
passed. Structured results report the decode probe PASSED through cleanup and
RGB-to-YUV conversion. This validates the decoder-owned path, not the unsafe
convenience API.

A dependency action audit covering source_components and the decode probe found
zero foreign/CMake actions, with 24,493 CppCompile actions as positive control.
Local analysis executes zero build actions. This does not establish a complete
Electron build; full source profiles still cover Linux AMD64 only.

## Blink generator prerequisites

Original Web IDL collections/database, testing IDLs and event-name generation
passed hosted validation at `d8f41f0`: [components](https://formatjs.buildbuddy.io/invocation/17d61bc5-9c85-42e3-b767-6c12ff2c63ad),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/8da194fe-2a3c-4810-bfb3-0511e977fbbd),
and [cross probes](https://formatjs.buildbuddy.io/invocation/e24e7dad-0ea7-43c3-ae99-8297cecda790).
The structured binding probe reports PASSED, checking event inheritance,
component ownership, export metadata and native header paths. Generator actions
also verify equal output across changed source paths and mtimes.

`3888599` adds 17 original platform generators and declared native gperf
3.1.bcr.2. Its 26-generator dependency audit found zero foreign/CMake actions;
387 CppCompile actions provide a positive control. Local analysis executed zero
build actions. [Expanded components](https://formatjs.buildbuddy.io/invocation/e785ce31-c508-4289-8682-74c882a0d81c),
[BCR consumer](https://formatjs.buildbuddy.io/invocation/6b4b6575-b6d1-4f25-927f-a2f452add7bb)
and [cross probes](https://formatjs.buildbuddy.io/invocation/21c8bec0-ce34-4508-9318-393ad4b810e0)
passed. The aggregate profile records all 26 generator actions, including native
gperf generation; the full source suite reports the binding probe PASSED.

Generated compilation headers now follow native C/C++ owners. Their selected
set matches the pre-IDL profile; auxiliary testing headers stay outside unrelated
compilations. Full Blink and Electron integration remain unfinished.


The source overlay at `0f2b70e` passed its [hosted BCR consumer](https://formatjs.buildbuddy.io/invocation/d95c2ae9-2364-4e15-a145-bc7d59516f3a),
including Catapult, tracing WebUI, policy, CUPS/xshmfence ABI, Blink and
DevTools probes. Its [full components build](https://formatjs.buildbuddy.io/invocation/c69cb285-f229-4804-84ed-8443dd4105fb)
failed on missing declared headers and security interstitial JavaScript inputs.
Full source linkage remains open.


The `f5c3c64` [hosted consumer](https://formatjs.buildbuddy.io/invocation/be316b86-96a8-438b-8535-8aa994afef56)
has passed the original fuse/Node artifact comparison and SDK runtime ABI
contract including GdkPixbuf. Full consumer/components execution remains pending;
these probes do not establish complete Electron linkage.


The completed `f5c3c64` [consumer](https://formatjs.buildbuddy.io/invocation/be316b86-96a8-438b-8535-8aa994afef56)
and [cross checks](https://formatjs.buildbuddy.io/invocation/9c18ca24-2a0f-4ede-8b18-fd1fc08568c4)
passed. Final [components diagnostics](https://formatjs.buildbuddy.io/invocation/85913fe9-8c99-4429-b33b-da606236117f)
reported only the missing notification header and nested DomDistiller input.
The source overlay now pins those interfaces/assets and expands the full app
resource closure; hosted validation of those changes remains required.
