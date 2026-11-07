# Performance

Build isolation comes first; see [hermeticity](hermeticity.md). All measurements
come from BB. Native GH jobs execute artifacts only.

Current changes:

- `remote_download_toplevel` keeps intermediate compiler outputs remote.
- `remote_cache_compression` compresses CAS transfers.
- Root cross-build fixtures use one split-transition graph instead of seven
  sequential builds with platform changes. Target programs never execute.
- BB uploads separate fixture and app-matrix Chrome traces. Diagnostics verify
  their CAS digest, repository and commit before reporting timings.
- Native smoke uploads the already-compressed BB ZIP with
  `compression-level: 0`, avoiding another deflate pass. This follows the
  [artifact action's guidance](https://github.com/actions/upload-artifact#altering-compressions-level-speed-v-size)
  for large incompressible files; product bytes remain unchanged.

## Recorded observations

Before the split graph, [a7ffa3c](https://formatjs.buildbuddy.io/invocation/14a307f5-04ba-4de6-bf8e-212d2e8d4dac)
spent 31.858 seconds across seven fixture builds, then 44.309 seconds building
the desktop matrix. The matrix trace had a 15.970-second critical path.

With the split graph, [30adfbd](https://formatjs.buildbuddy.io/invocation/981b44ee-f61e-4b91-9f1e-673cb84978fe)
spent 28.735 seconds on fixtures and 33.573 seconds on the desktop matrix.
Trace critical paths were 2.169 and 3.702 seconds respectively.

These runs have different cache populations. They establish observations, not a
controlled speedup. Build durations come from child invocation metadata;
overlapping trace event durations must not be summed as wall time. Action counts
reported by BB include analyzed/cached work and are not executed-action counts.

Both runs produced a 1,226,193,950-byte smoke archive. Size equality alone does
not establish byte equality. Native launch, DEB install, checksum rejection,
two-version update and uninstall checks remain required.

For the same verified BB archive from `30adfbd`, the GH upload step took
[37 seconds with default compression](https://github.com/formatjs/rules_electron/actions/runs/42344250651)
and [13 seconds with compression disabled](https://github.com/formatjs/rules_electron/actions/runs/42344491193).
Outer artifact sizes were 1,224,404,379 and 1,226,194,112 bytes respectively:
about 1.8 MB more transport for avoiding the extra compression pass. These are
individual hosted-run observations, not a guaranteed latency reduction.

A [fresh packaging run at c940051](https://formatjs.buildbuddy.io/invocation/c27517cc-eeca-4e1e-8f49-e14bb2736a05)
recorded 122.001 seconds for the smoke ZIP action, versus 6.279 seconds for the
slowest app assembly action. Matrix build time was 156.966 seconds. The smoke
transport now uses deflate level 1 and stores already-compressed DEB members.
macOS app ZIP members still need outer compression: their inner ZIP uses stored
entries. ZIP transport preserves the signed bundle's symlinks and modes.
Installer member bytes remain unchanged.

The [first run at 034b88e](https://formatjs.buildbuddy.io/invocation/86c05464-b927-4a36-b6e8-fa685fbb4c46)
recorded 63.334 seconds for that action and a 1,305,277,354-byte archive,
versus 122.001 seconds and 1,226,193,952 bytes before the compression change.
That trades about 79 MB more transport for lower observed packaging latency.
Whole-build cache populations differed; these action observations do not prove
an equivalent whole-workflow speedup. Native handoff and download costs still
need measurement across repeated runs.

Adding source-built execution Node for Windows resources introduced a separate
cold-tool cost. The [first matrix at 763bf8c](https://formatjs.buildbuddy.io/invocation/e220bf85-35ba-4c06-afde-62e9981e622a)
took 485.690 seconds. BB reported 4,675 completed remote executions,
11,653.833 CPU-seconds and a maximum per-action peak of 2,461,839,360 bytes.
Those are whole-matrix observations, not Node-only totals. Worker input downloads
were 68,089,242,198 bytes; worker output uploads were 3,531,454,080 bytes. These
cumulative worker transfers include repeated inputs across actions and are not
client download sizes. The smoke ZIP action took 58.851 seconds.

Diagnostics now report resource snapshots and execution stages alongside trace
profiles. They validate the child invocation's repository and commit before
querying execution metadata, and print aggregate metrics rather than commands,
worker identities or environment. Test/cache counts still need separate
interpretation: remote execution records omit ordinary remote action-cache hits.

The first NSIS lifecycle run exposed weak differential reuse with fixed chunks:
x64 downloaded 125,250,761 of 125,316,297 installer bytes; ARM64 downloaded
124,890,889 of 124,956,425 bytes. Each reused only one 64 KiB chunk. Installer
header length changes shift subsequent byte offsets, so block boundaries must
resynchronize on content. New v2 maps use bounded gear chunks with SHA-256;
the native gate now requires fewer than half the installer bytes over ranges,
with no full-download fallback.

Content-defined maps alone still transferred about 97% with a solid compressed
payload. Independent per-file LZMA2 streams address that second source of churn.
In [39cda07 native smoke](https://github.com/formatjs/rules_electron/actions/runs/42351884226),
x64 downloaded 776,681 of 96,256,700 bytes (0.81%); ARM64 downloaded 760,466 of
89,390,353 bytes (0.85%). Both completed install, update, native launch and
uninstall. These measure the sample's version-only update; broader application
changes need separate measurements. The 50% native transfer gate remains active.

## Source dependency baseline

The Electron overlay's [4cdf425 BCR consumer build](https://formatjs.buildbuddy.io/invocation/70b2e6ab-afea-43f1-9eeb-4b68b00000b5)
validated eight newly declared Node dependencies (133 C/C++ units) and their
linked behavior probe. BB recorded 135 completed remote executions, 35.390
CPU-seconds and maximum per-action peak memory of 224,722,944 bytes. Worker
input/output totals were 125,700,457 and 8,663,136 bytes. These cover the consumer
source-test build, not only the eight libraries; local test execution on the BB
workflow host and repository fetching are outside those remote-action totals.
The parallel component build reused cached work, so these observations do not
establish a controlled cold-build duration or speedup. Full Electron linking and
its performance baseline remain pending.

The [93dc092 Torque consumer](https://formatjs.buildbuddy.io/invocation/e338b62e-75ae-4a3e-b5fd-21279b2f4cd3)
passed full generation and reproducibility checks. Its source-test child recorded
one remote execution: 17.370 CPU-seconds, 182,996,992 bytes peak memory,
4,961,706 bytes downloaded and 18,232,433 bytes uploaded by the worker.
Compiler work was already cached; these totals exclude cache hits and tests
executed on the BB workflow host. They establish an observation for this warm
consumer run, not a cold compiler-build cost or measured speedup. The producer
currently runs Torque twice to enforce path/mtime reproducibility; any future
reduction must retain that check in hosted validation.

The [fe62420 component workflow](https://formatjs.buildbuddy.io/invocation/63616e6c-424b-4f71-8962-5903b4a10113)
validated the captured 445-unit ICU profile. Its source-test child recorded 447
remote executions, 145.257 CPU-seconds, 119,283,712 bytes maximum per-action peak
memory, 129,821,471 worker input bytes and 38,243,742 worker output bytes. These
are phase totals, excluding cached actions, repository fetching and tests on the
BB workflow host. The concurrent consumer reused compiled work; neither run is
a controlled cold-build timing comparison. ICU repository setup now lives in
its own module, keeping Node/V8 repository definition files unchanged during
ICU-specific edits.

The build-only source-component phase now uses
`--remote_download_outputs=minimal`, keeping its compiled archives in BB CAS.
The following test phase still downloads declared executables and runtime data.
[598ad7f components](https://formatjs.buildbuddy.io/invocation/f44f8363-7202-48e8-bcc4-d032c436f37b)
and [consumer](https://formatjs.buildbuddy.io/invocation/9432732a-4bff-49ce-8cba-9d8c6df348e6)
passed with this split. No client-download byte delta or latency speedup has
been measured yet.

The successful [PartitionAlloc archive-build phase](https://formatjs.buildbuddy.io/invocation/962f5cb8-f930-48e9-b317-f8b4a1cb83b4)
recorded 68 remote executions, 25.229 CPU-seconds, 144,891,904 bytes maximum
per-action peak memory, 8,629,907 worker input bytes and 7,254,225 worker output
bytes. Archive inputs remained unchanged through the fully passing 5b7f211
validation. These are build-phase observations, excluding cache hits,
repository fetching and native tests; concurrent workflows shared cached work.
They do not establish a controlled cold-build cost.

V8's repository BUILD template now delegates to a stable source macro. New
generator/library rule definitions can change without editing that template.
No fetch-time reduction has been measured.

The [3278609 Temporal archive phase](https://formatjs.buildbuddy.io/invocation/7fe1b48b-5a13-4131-b657-68cac3c348f9)
recorded 435 remote executions, 114.034 CPU-seconds, 734,355,456 bytes maximum
per-action peak memory, 10,308,441,961 worker input bytes and 87,548,240 worker
output bytes. This includes executed prerequisite/tool actions; it is not a
Temporal-only compile cost. Worker input totals count transfers across actions,
not unique source bytes. Concurrent component/consumer builds shared cached work.
These totals exclude cache hits, repository fetches and tests on the BB host;
no controlled cold/warm speedup has been measured.

The [687dc7f Protobuf archive phase](https://formatjs.buildbuddy.io/invocation/e04577a8-3b54-4f2f-81df-4da0306ebe58)
recorded 129 remote executions, 293.384 CPU-seconds, 493,834,240 bytes maximum
per-action peak memory, 955,499,002 worker input bytes and 47,699,407 worker
output bytes. These are executed-action phase totals, including prerequisites;
they exclude cache hits, repository fetching and tests on the BB host.
Concurrent consumer builds shared cached work. They do not establish a cold-build
cost, per-library cost or speedup.

The [7177c35 Perfetto consumer phase](https://formatjs.buildbuddy.io/invocation/6db0fa69-6615-4b82-b39f-b26278ecd0a7)
recorded 669 remote executions, 480.165 CPU-seconds, 657,432,576 bytes maximum
per-action peak memory, 981,194,544 worker input bytes and 51,709,220 worker
output bytes. This phase includes prerequisite, compiler and generator work;
each original generator verifies path/mtime reproducibility with two executions.
The [component archive phase](https://formatjs.buildbuddy.io/invocation/93c83515-1a60-4739-9934-68ddaaec62c9)
reused compiled work and recorded 113 executions totaling 1.163 CPU-seconds.
These are separate phase observations sharing a cache, excluding cache hits,
repository fetching and tests on the BB host. Neither phase measures a controlled
cold-build cost or latency improvement.

The [4516ed7 full V8 component phase](https://formatjs.buildbuddy.io/invocation/05b4ba5f-3c5e-444b-b9c1-b05160073fb9)
completed in 356.592 seconds. BB recorded 2,744 remote executions totaling
20,648.053 CPU-seconds, 1,845,444,608 bytes maximum per-action peak memory,
792,480,712 worker input bytes and 638,456,960 worker output bytes. The phase
includes prerequisites, target/execution configurations and reproducibility
runs; it is not a per-library compiler benchmark. Remote totals exclude cache
hits, repository fetching and tests on the BB host. Prior attempts and the
concurrent consumer populated a shared cache, so this is not a controlled cold
build or speedup comparison. Phase duration includes frontend/orchestration work
that the remote CPU totals do not measure.

A [documentation-only 9332ee8 repeat](https://formatjs.buildbuddy.io/invocation/fbb682d8-bce5-4b30-b743-02739be00e1c)
kept engine/product inputs and the source-component target set unchanged. Its
warm build phase completed in 16.234 seconds with zero tracked remote executions;
source-test phase completed in 1.377 seconds, also without remote executions.
The separate fresh network-denial gate still executed two actions. This records
warm-cache behavior, not a controlled cold/warm speedup or absence of frontend,
repository or BB-host work.

## Smoke transport

The [33244d8 matrix](https://formatjs.buildbuddy.io/invocation/2862db5f-beee-4568-bb0e-0ba735d29433)
produced a 1,676,779,799-byte smoke ZIP, verified before GH handoff. Four native
hosts each download that full archive: roughly 6.71 GB of archive payload across
those hosts, excluding the bridge and protocol overhead. All four
[native jobs passed](https://github.com/formatjs/rules_electron/actions/runs/42352517657),
including the public macOS release ZIP. This established the repeated-download
baseline before splitting transport.

The current handoff emits four BB-built archives and routes each to its matching
native host. One action checks all seven apps before writing any shard; Linux
ARM64 apps/packages remain declared inputs. Repository/commit/success/CAS checks
apply separately to each download.

The [be8daa1 BB run](https://formatjs.buildbuddy.io/invocation/ba65c2ed-02c5-461d-a911-615b2735de11)
produced these verified archive sizes:

- Linux x64: 316,255,386 bytes.
- macOS ARM64: 124,103,453 bytes.
- Windows ARM64: 450,950,508 bytes.
- Windows x64: 468,552,784 bytes.

Native-host archive payload totals 1,359,862,131 bytes, versus 6,707,119,196 bytes
for four copies of the previous aggregate: 79.7% less. This excludes bridge and
protocol overhead. Both Windows compiler variants remain in each CPU's shard;
Linux ARM64 apps/packages remain BB inputs without native transport.
[All four native jobs passed](https://github.com/formatjs/rules_electron/actions/runs/42353252280),
including DEB/NSIS lifecycle checks, integrity enforcement and macOS signatures.
NSIS differential byte counts remained 776,681 on x64 and 760,466 on ARM64.

The matrix took 114.329 seconds; its bundle trace event lasted 72.136 seconds.
BB reported two completed executions totaling 58.680 CPU-seconds, with maximum
per-action peak memory 1,408,147,456 bytes. These are whole-matrix execution
statistics, not bundle-only resources. Cache populations differ from earlier
runs; the transfer reduction does not establish a build-latency improvement.

## Chromium base baseline

The [4746f81 source build](https://formatjs.buildbuddy.io/invocation/9cc4e6a6-ac49-484f-9f2b-592a8fceefe0)
passed in 42.111 seconds. BB tracked 431 remote executions, 471.481 CPU-seconds,
389,984,256 bytes maximum per-action peak memory, 1,812,107 worker input bytes
and 1,378,391 worker output bytes. The following source-test phase took 8.202
seconds and passed original Rust JSON and native GLib dispatch checks, alongside
the existing source probes. Its two remote executions include compile/link work;
tests execute on the matching Linux BB workflow host.

The documentation-only [7e1a046 repeat](https://formatjs.buildbuddy.io/invocation/9b63799e-e08c-4df8-9848-e4d91d42ba10)
used the same product inputs: source build 26.952 seconds, tests 1.711 seconds,
zero tracked remote executions in either phase. The separate fresh network gate
still executed two remote actions.

These are phase observations with shared caches and prior compilation attempts,
not a cold Base/Electron benchmark. PartitionAlloc's added two-unit `raw_ptr`
target keeps its headers separate from the existing allocator target, preserving
full V8 compiler inputs. Actual cold/warm comparisons remain required before
claiming a build speedup.

## Patched libnode baseline

The [40b2baf source phase](https://formatjs.buildbuddy.io/invocation/fff21035-a502-4b76-bd47-f8381b43a554)
passed in 19.759 seconds. BB tracked two remote executions, 1.958 CPU-seconds,
205,860,864 bytes maximum per-action peak memory, 54,217 worker input bytes and
27,114,272 worker output bytes. Most compilation was cached from prior attempts;
these are phase totals, not a cold 239-unit libnode build.

The following [source-test phase](https://formatjs.buildbuddy.io/invocation/1666c188-b18d-4ff3-b11c-2da7548b85b8)
took 5.609 seconds and passed native Node API, addon, event-loop and shutdown
checks alongside existing probes. Two tracked remote executions used 1.257
CPU-seconds, 116,781,056 bytes maximum per-action peak memory, 43,998 worker input
bytes and 109,462,531 worker output bytes. Runtime tests execute on the matching
Linux BB workflow host; their resources are outside remote-execution totals.

The documentation-only [7df70c4 warm repeat](https://formatjs.buildbuddy.io/invocation/f9dfc3a8-0dbb-414d-aa80-5776f48e9d9b)
used the same product inputs: source phase 17.614 seconds, tests 3.160 seconds,
zero tracked remote executions in either phase. The independent fresh network
gate still executed two remote actions. Cached successes do not measure a fresh
runtime execution or a cold source build.

Header groups keep Brotli/Zstd independent from Node header changes. The isolate
lifecycle fix changes one owned C++ source; existing V8 and Base compiler inputs
stay shared. No cold-build speedup or complete Electron baseline is claimed.

## Gin and i18n baseline

The [406dda7 source phase](https://formatjs.buildbuddy.io/invocation/cb9396bb-3fbd-4a60-80c3-6f96840ac210)
compiled the 56 new Gin/i18n/CED units in 23.678 seconds. BB tracked 61 remote
executions, 42.931 CPU-seconds, 314,667,008 bytes maximum per-action peak memory,
24,146,031 worker input bytes and 7,672,202 worker output bytes. The following
runtime probe exposed caller file-API errors; these were fixed before acceptance.

The [5bca689 source phase](https://formatjs.buildbuddy.io/invocation/1f47a268-a4cb-4f9e-9224-380654dfb17c)
passed in 19.728 seconds with zero tracked remote executions. Its
[source-test phase](https://formatjs.buildbuddy.io/invocation/b334726a-a467-458c-8719-0c59a14111d4)
passed in 6.747 seconds: two remote executions, 3.764 CPU-seconds, 231,620,608
bytes maximum per-action peak memory, 43,145 worker input bytes and 78,383,588
worker output bytes. Native probes run on the matching BB Linux host; remote
resource totals exclude their execution. The separate fresh network gate
executed two actions.

Shared Base/V8/ICU targets and separate header groups preserve existing compiler
inputs. These phases shared caches with earlier attempts and the consumer
workflow; they do not establish a cold-build baseline or speedup.

## IPCz baseline

The [c961819 source phase](https://formatjs.buildbuddy.io/invocation/8bd20248-90fc-4497-851d-e57664e37a60)
passed in 21.754 seconds. BB tracked 39 remote executions, 44.859 CPU-seconds,
246,165,504 bytes maximum per-action peak memory, 24,693,779 worker input bytes
and 6,615,552 worker output bytes. The 36-unit core reuses existing Base/Abseil
targets; their compiler inputs stay unchanged.

The [source-test phase](https://formatjs.buildbuddy.io/invocation/030f953c-f7c2-4f4a-925d-7b2bba82e83b)
passed in 6.381 seconds, including actual IPCz broker/client messaging and portal
transfer. Six remote executions used 3.089 CPU-seconds, 150,171,648 bytes maximum
per-action peak memory, 220,098,002 worker input bytes and 6,945,670 worker output
bytes. The original four-unit reference driver is test-only. Runtime probes run
on the matching BB Linux host, outside those remote-resource totals. The separate
fresh network gate executed two actions.

Concurrent component/consumer workflows shared caches. These phase totals exclude
cache hits and repository fetching; they do not establish a cold-build speedup.

## Mojo and network baseline

The [9b5017c source phase](https://formatjs.buildbuddy.io/invocation/c1c044c9-0be1-4d3a-83ee-e165892c18f0)
passed in 82.057 seconds. BB tracked 1,021 remote executions, 1,785.958
CPU-seconds, 860,741,632 bytes maximum per-action peak memory, 146,799,856 worker
input bytes and 16,969,031 worker output bytes. This includes the captured
1,124-unit closure and its native dependencies, with shared work cached from
earlier attempts and the concurrent consumer. It is not a cold-build baseline.

After probe API/import fixes, [122f977's source phase](https://formatjs.buildbuddy.io/invocation/7716389a-94a9-44d1-8e68-57b03159492d)
passed in 33.257 seconds with zero tracked remote executions. Its
[source-test phase](https://formatjs.buildbuddy.io/invocation/e7cd4545-a09e-4db4-b3ad-35ddcc1b17d2)
passed in 5.537 seconds, also with zero tracked remote executions. Source library
inputs stayed the same; runtime results and the nonce conformance test passed.
The separate fresh network gate executed two actions. Cache hits, repository
fetches and tests on the BB host are outside remote-resource totals.

The construction-tag target now declares one 1,359-byte header, previously 345
Mojo headers totaling 1,411,365 source bytes. Other consumers retain their needed
headers. These are declared source inventories; transfer costs depend on shared
inputs and worker caches. No build-latency speedup is claimed.

## Typed Mojo baseline

[8261fc4 source phase](https://formatjs.buildbuddy.io/invocation/21e101da-a6db-4da6-9fa2-451eb147674c)
passed in 42.804 seconds: 256 tracked remote executions, 288.125 CPU-seconds,
428,400,640 bytes maximum per-action peak memory, 391,488,475 worker input bytes
and 36,153,170 worker output bytes. The added closure contains 214 C++ units,
29 original generator actions and 694 declared generated outputs. Existing
native dependencies remain shared. Cache reuse and the concurrent consumer
prevent treating this as a cold-build baseline.

The [source-test phase](https://formatjs.buildbuddy.io/invocation/42e4bab2-6a1a-4331-86c4-b67de1391b5e)
passed in 5.067 seconds with zero tracked remote executions. Tests execute on
the matching native BB host; these resource totals exclude host test work,
cache hits and repository fetching. Sharing all 345 Mojo headers avoids a
second source projection; no latency speedup is claimed.

## Font and XML dependency baseline

[854f6a7 source phase](https://formatjs.buildbuddy.io/invocation/abdd8cc4-aa16-46fe-83b7-fd9c8420b9ac)
passed in 46.576 seconds: 73 tracked remote executions, 157.227 CPU-seconds,
411,340,800 bytes maximum per-action peak memory, 70,957,745 worker input bytes
and 13,321,016 worker output bytes. The new closure contains 142 C/C++ units;
shared dependencies and concurrent consumer/cache reuse make this a partial
execution baseline, not a cold build.

The [source-test phase](https://formatjs.buildbuddy.io/invocation/aecf0d4b-3b16-40fe-b259-794623a61722)
passed in 3.879 seconds with zero tracked remote executions. Native BB-host test
work, cache hits and repository fetching are outside these remote totals. These
numbers establish cost for this added closure; they do not establish a speedup.

## Fontconfig/fontations baseline

[6652729 source phase](https://formatjs.buildbuddy.io/invocation/b42db66f-63c0-4e3c-90c0-63831a5ac5ae)
passed in 24.318 seconds with zero tracked remote executions. Its
[source-test phase](https://formatjs.buildbuddy.io/invocation/f3ea78af-53ef-48ef-ab48-9330c2896356)
passed in 27.225 seconds with 62 tracked remote executions, 42.734 CPU-seconds,
673,886,208 bytes maximum per-action peak memory, 1,134,581,765 worker input bytes
and 43,389,152 worker output bytes. The new closure adds 29 C units, nine Rust
library/proc-macro targets, one build script and two native bindgen boundaries.

The test phase includes required compilation/link dependencies; runtime tests
execute on the matching native BB host. Resource totals exclude host test work,
cache hits and repository fetching. Concurrent consumer/cache reuse prevent a
cold-build claim; worker-input totals do not measure unique source bytes. Keep
this transport baseline when evaluating Rust/header input reduction.

## Native codec baseline

The [first successful codec source phase](https://formatjs.buildbuddy.io/invocation/7264cf87-dad1-48e3-9be6-c6142e577ca9)
passed in 33.586 seconds: 108 tracked remote executions, 22.374 CPU-seconds,
127,188,992 bytes maximum per-action peak memory, 622,645,539 worker input bytes
and 6,402,976 worker output bytes. The declared closure contains 213 product C
units, 81 execution-tool C units and 27 SIMD assembly actions. Shared cache and
the concurrent consumer make this partial execution coverage, not a cold build.

After correcting C linkage in the probe, [a4c1c6a's source phase](https://formatjs.buildbuddy.io/invocation/1c5227bb-2570-4d87-94c2-04fcfb6192ef)
passed in 28.449 seconds and its [source-test phase](https://formatjs.buildbuddy.io/invocation/98600e49-1567-4058-b418-772667add439)
passed in 3.907 seconds, both with zero tracked remote executions. Native BB-host
test work, cache hits and repository fetching remain outside these remote totals.
The aggregate excludes a redundant target-platform NASM build; execution-platform
NASM remains required by the original assembler actions. No timing speedup is
claimed from that dependency choice.

## Complete matching Skia baseline

[3d7a5d1 source phase](https://formatjs.buildbuddy.io/invocation/6d4a85bd-1ea5-4f41-aa66-730257cf4ff3)
passed in 128.073 seconds: 1,559 tracked remote executions, 3,246.895 CPU-seconds,
855,576,576 bytes maximum per-action peak memory, 1,780,802,357 worker input bytes
and 66,725,155 worker output bytes. The added closure contains 1,158 C++ units,
15 original generator actions and 12 Rust targets. Shared header-provider fixes
also affect existing consumers. Earlier attempts and the concurrent consumer
supply cache reuse, so this is not a cold-build baseline.

The [source-test phase](https://formatjs.buildbuddy.io/invocation/117fe0b2-28c9-44c0-ab64-7d460f467448)
passed in 5.853 seconds with zero tracked remote executions. Native BB-host test
work, cache hits and repository fetching remain outside these remote totals.
The shared Rust profile retains its previous 95 target records; shared Base,
fonts and codecs keep their native implementations. Compare equivalent cache
conditions before reducing header contexts or parallelizing generators; preserve
all GPU build configuration, runtime probes and generator byte checks.

## Native gfx baseline

[8f46f43 source phase](https://formatjs.buildbuddy.io/invocation/95f5aea4-975a-4764-9fe1-f2591bc1b5e1)
passed in 72.211 seconds: 343 tracked remote executions, 380.113 CPU-seconds,
448,229,376 bytes maximum per-action peak memory, 101,844,385 worker input bytes
and 519,593 worker output bytes. The closure adds 351 native units, 34 original
generator actions and four literal GN metadata targets. Earlier attempts and
the concurrent consumer supply cache reuse; this is not a cold-build baseline.

The [source-test phase](https://formatjs.buildbuddy.io/invocation/ac6cc149-8ad6-474b-9b53-17d8a9f818fa)
passed in 8.708 seconds: one tracked remote execution, 0.822 CPU-seconds,
331,943,936 bytes maximum per-action peak memory, 225,665,891 worker input bytes
and 10,209,479 worker output bytes. Native BB-host test execution, cache hits and
repository fetching remain outside these remote totals. Large shared header
contexts are a candidate for measurement once full Electron links; preserve
original configuration, assembly includes and generator reproducibility checks.

## Native display baseline

[81686a0 consumer source-test phase](https://formatjs.buildbuddy.io/invocation/54e83ecb-cff0-4833-b22a-324dbd0b4d35)
passed in 63.484 seconds: 144 tracked remote executions, 208.432 CPU-seconds,
428,597,248 bytes maximum per-action peak memory, 666,914,846 worker input bytes
and 28,028,320 worker output bytes. The closure adds 118 native units and 21
original generators. Source-relative Mojo AST metadata and the corrected Python
hash-seed launcher also affect existing generator consumers.

The concurrent [source phase](https://formatjs.buildbuddy.io/invocation/24265d9e-f877-4771-bb1a-f7d58a101e8d)
passed in 77.068 seconds with 13 tracked remote executions, 0.183 CPU-seconds,
109,076,480 bytes maximum per-action peak memory, 1,203,211 worker input bytes
and 1,376,349 worker output bytes. Its [source-test phase](https://formatjs.buildbuddy.io/invocation/90e71786-a985-4a0f-a2d0-3ebdaf4d4b8b)
passed in 8.077 seconds with zero tracked remote executions. Earlier attempts
and the consumer populated shared caches; these are not cold-build measurements.
Native BB-host tests, cache hits and repository fetching remain outside the
remote resource totals. No speedup is claimed from these mixed-cache runs.

## Next measurements

Repeat the same target set and product inputs with explicit cold/warm cache
conditions. Record workflow and child build durations, analysis time, actual
executed/cache-hit counts, executor CPU/peak memory and transfer bytes. Keep
fixture and desktop workspaces separate in reports.

The smoke archive duplicates runtime bytes across unpacked apps, DEBs and Windows
compiler variants. Measure execution
time and transferred bytes before changing compression or transport layout;
preserve every target, exact installer bytes, symlink/mode metadata and native
coverage. Complete Electron compilation needs its own baseline once that runtime links.
