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
- Smoke ZIPs store `.7z` and `.lz` packages directly, alongside existing stored
  DEB/NSIS/AppImage members. This avoids deflating the examples' compressed
  payloads again. Product archive generation remains unchanged.

## Recorded observations

For Linux x64 smoke packing, [8ec226b](https://formatjs.buildbuddy.io/invocation/769e347f-4145-49e0-8e55-2b9734638a2e)
recorded 31.781 seconds of worker execution and 31.509 CPU-seconds. After storing
`.7z`/`.lz` members, [b21a900](https://formatjs.buildbuddy.io/invocation/dc54d008-fc83-4b23-8a3a-814313b02c10)
recorded 23.074 seconds and 22.496 CPU-seconds. Linux shard sizes were
1,190,982,005 and 1,190,909,270 bytes. Reported worker peak memory was higher:
1,128,337,408 versus 2,310,795,264 bytes. Different worker/cache conditions prevent
a controlled whole-build speedup claim. Both commits passed all four native hosts;
the product archive algorithms did not change.

The [0b869ae matrix](https://formatjs.buildbuddy.io/invocation/aca4f1f5-ccaf-4d7e-bdb8-4fe543a52fa4)
records one 160.846-second smoke archive action and a 285.545-second critical
path. The slowest app assembly took 6.089 seconds. Smoke transport now has four
independent archive actions behind a shared seven-app architecture gate. Each
archive receives only its shard's payloads; build-only Linux ARM64 packages remain
inputs to the validation gate. Archive compression, member ordering and bytes
stay unchanged.

The [5869ebd matrix](https://formatjs.buildbuddy.io/invocation/31076533-be8e-4087-a160-96ae8d2d61ca)
passes with four archive actions: maximum 46.033 seconds, cumulative 127.078
seconds. The shared validation gate takes 3.401 seconds. All four archive
SHA-256 hashes and sizes match `0b869ae` exactly, totaling 2,855,094,961 bytes.
The new trace's critical path is 52.038 seconds; different compiler/package cache
populations prevent a controlled whole-build comparison. Overlapping archive
action times are not wall time and must not be summed as workflow duration.

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

The [3fe910c source example](https://formatjs.buildbuddy.io/invocation/710b3025-44c4-4a72-abd7-8750ffc66060)
hit BB's free-tier deadline at 3600.484 seconds. Its authenticated, SHA-verified
truncated profile contains 2769.954 seconds of recoverable trace. Complete events
record 27,317.719 cumulative seconds in `MerkleTreeComputer.buildForSpawn`,
55,018.082 waiting on its preparation/upload semaphore, and 1026.622 in worker
execution. GC events record 611.077 seconds. These overlap; they are neither
additive wall time nor a complete critical path. Cache warming alone did not
finish the graph.

BB rejected the 64 GB frontend trial before startup: this organization permits
at most 32 GiB per runner. The next trial requests 16 CPUs, retaining 32 GB RAM
and the 24 GB heap used by the 8-CPU baseline. Worker platform, compiler options and source pin
stay unchanged so existing action-cache entries remain usable. This tests a
frontend CPU/memory hypothesis; no speedup or completed source desktop is claimed.
Failed-run profile recovery is bounded to 128 MiB expanded data, retains only
complete JSON events, and reports fixed public operation names without paths.
Recovery counts and discards invalid timing records; complete profiles retain
strict timing validation. Recovered timings remain partial observations.

The [16-CPU trial](https://formatjs.buildbuddy.io/invocation/8a01b8d6-6c78-4df9-9b63-2f3bc4f413fc)
also hit the free-tier deadline (3600.252 seconds), reaching a reported
119,830/132,406 actions. More requested CPUs did not complete the graph.
The next trial retains 16 CPUs/32 GB and the 24 GB heap, adding
`--discard_analysis_cache` only to the final build. Bazel documents this flag as
freeing analysis memory during execution while retaining the on-disk action cache
([memory guide](https://bazel.build/advanced/performance/memory)). This tests
memory pressure rather than changing compiler inputs. CPU visibility is logged
before setup; no completion or speedup is claimed.

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

## Native events baseline

[0e175df source phase](https://formatjs.buildbuddy.io/invocation/9c68768b-b739-4e40-bd3d-25542b0cfac8)
passed in 68.359 seconds: 429 tracked remote executions, 669.929 CPU-seconds,
460,480,512 bytes maximum per-action peak memory, 912,670,319 worker input bytes
and 20,338,085 worker output bytes. The captured closure adds 417 native units,
76 original generators and protocol copies. Native XCB adds 31 original protocol
generator runs, declared header copies and its C implementation; XKB builds its
parser from source. Earlier attempts and concurrent consumers populated caches.

[decd4f5 source phase](https://formatjs.buildbuddy.io/invocation/5488cb9f-bc8a-4f6b-bee2-6f5468833f12)
passed in 53.771 seconds and its [source-test phase](https://formatjs.buildbuddy.io/invocation/72ccdd03-8ded-407d-870c-bd834c22f9a1)
passed in 10.744 seconds, both with zero tracked remote executions. Native
BB-host tests, repository fetching and cache hits remain outside the remote
resource totals. [076dc2e consumer](https://formatjs.buildbuddy.io/invocation/3b776ef1-7a74-44e3-a5b5-474214e5a32a)
passed the final probe including malformed-display rejection with valid output
arguments. These mixed-cache phases establish coverage and resource observations,
not a cold-build baseline or speedup. Preserve full protocol generation and
byte checks when measuring narrower header contexts later.

## Native UI/WebUI resource baseline

The complete UI closure retains original typecheck/lint/minification and resource
generation, including byte checks across source paths and mtimes. Shared npm
source groups avoid repeating package file lists in each action. Generated
predecessor outputs, TypeScript declarations and static resource bytes remain
declared inputs.

[db647f4 source build](https://formatjs.buildbuddy.io/invocation/61774164-a340-4eb5-83dd-19e8760b868e)
passed in 44.835 seconds with 121 tracked remote executions, 118.213 CPU seconds,
450,105,344-byte maximum action peak memory, 1,285,751,929 input download bytes
and 16,189,921 output upload bytes. Earlier attempts and concurrent consumers
had populated caches; this is not a cold-build measurement.

The final [2b46400 source build](https://formatjs.buildbuddy.io/invocation/4c6921c7-c5fc-4616-9a2b-7c9c65a6725f)
passed in 37.979 seconds and its [source tests](https://formatjs.buildbuddy.io/invocation/6cba1c36-a27e-4725-9368-45cdeb1c234f)
passed in 6.358 seconds, both with zero tracked remote executions. The
[BCR consumer](https://formatjs.buildbuddy.io/invocation/c1ddb72f-d5fb-446f-8cb4-ea7e8e39da31)
also passed real native UI and generated-module probes. Cache hits, repository
fetching and BB-host test execution remain outside those remote resource totals.
These phases establish coverage and resource observations, not a measured speedup.

## Native Ozone/GL source build

The [a6469fa source aggregate](https://formatjs.buildbuddy.io/invocation/85cc8487-a8b3-48f3-88d9-3bd196ca972e)
built in 222.281 seconds: 1,656 tracked executions, 3,802.833 CPU seconds,
1,538,920,448-byte maximum action peak memory, 2,675,640,958 input download bytes
and 88,897,171 output upload bytes. Earlier attempts and concurrent consumers
had populated caches; this is a mixed-cache build, not a cold baseline.

This covers compilation and declared generators for 2,147 native Ozone/GL units.
The subsequent test phase stopped at link because desktop SDK dependencies need
newer glibc symbols than the default target supplied. Upstream now selects its
explicit glibc 2.31 source platform; runtime validation remains pending. These
figures establish build coverage, not graphics correctness or a speedup.

## Native graphics runtime validation

The [e42592d graphics probe](https://formatjs.buildbuddy.io/invocation/e6945d5b-4ab5-42fe-929a-f983b435fc58)
passed in 136.353 seconds with four tracked executions, 0.980 CPU seconds,
521,826,304-byte maximum action peak memory, 71,869,219 input download bytes and
35,802,120 output upload bytes. The actual renderer and framebuffer checks passed;
this phase includes analysis/setup and shared-library linking, not only rendering.

Its [source aggregate](https://formatjs.buildbuddy.io/invocation/2a4d8abf-2bff-4752-81c2-6473b464cc21)
passed in 64.626 seconds and [complete suite](https://formatjs.buildbuddy.io/invocation/86c792ab-cf2a-44d2-a8b5-315e34668a45)
in 5.170 seconds, both with zero tracked remote executions. Prior attempts and
concurrent consumers had populated caches. These are mixed/warm observations,
not a cold-build baseline or measured speedup. BB-host test execution remains
outside remote CPU/memory totals. The clean
[e677b62 components](https://formatjs.buildbuddy.io/invocation/7056db57-2403-44a5-ac43-048b82fa95ec)
and [consumer](https://formatjs.buildbuddy.io/invocation/0109ff8b-c8e5-4faf-9cda-c333de0a4be3)
also passed after removing crash probes and the symbolizer.

SDK dependencies now import individual libraries; compilation-only providers no
longer pull entire desktop library sets into every DSO. Native GLib and zlib
shared owners prevent duplicated initialization state. Future measurements must
preserve the real loader, SwiftShader selection and framebuffer checks.

## GPU command-buffer source aggregate

The [7d07a48 source aggregate](https://formatjs.buildbuddy.io/invocation/2a50b8c8-2089-4c39-9950-a097be8b3f3e)
built 2,633 captured native units in 68.641 seconds: 624 tracked executions,
1,305.694 CPU seconds, 742,985,728-byte maximum action peak memory,
1,896,199,480 input download bytes and 80,179,315 output upload bytes.
The preceding graphics gate and concurrent BCR consumer had populated caches.
This is a mixed-cache observation, not a cold baseline or measured speedup.
Transport-probe runtime validation remains separate from aggregate compilation.

The expanded [5cb43b3 aggregate](https://formatjs.buildbuddy.io/invocation/db1109b0-980c-44fe-99f1-153b9efa8946)
built 2,639 units in 34.549 seconds with eight tracked executions, 24.255 CPU
seconds, 526,127,104-byte maximum action peak memory, 26,974,551 input download
bytes and 2,873,250 output upload bytes. Most existing outputs were already cached;
the target set changed, so these figures do not establish a speedup.

The validated [9a26e4a aggregate](https://formatjs.buildbuddy.io/invocation/2f4f54d6-0367-457d-b6aa-21c564d24ac5)
passed in 6.357 seconds with zero tracked executions. Its
[complete native suite](https://formatjs.buildbuddy.io/invocation/a2205917-022b-4e00-a863-c111dae2b214)
passed in 8.390 seconds with two tracked executions, 2.497 CPU seconds,
367,448,064-byte maximum action peak memory, 25,012 input download bytes and
3,302,529 output upload bytes. Earlier attempts populated caches; BB-host native
test execution remains outside those remote CPU/memory totals. These are warm
observations with passing behavior checks, not a cold/warm speedup comparison.

## Symphonia media dependency

The [bdd6d7e source aggregate](https://formatjs.buildbuddy.io/invocation/40786b09-0961-4775-aca8-6f40537092f7)
passed in 30.253 seconds with two tracked executions, 0.090 CPU seconds,
115,621,888-byte maximum action peak memory, 1,710,428 input download bytes and
11,540 output upload bytes. Its [complete native suite](https://formatjs.buildbuddy.io/invocation/0bb1fe8e-7bab-42eb-9eee-a3d994fa6a60)
passed in 12.989 seconds with zero tracked remote executions; native tests run on
the matching BB host.

The separate [BCR consumer test phase](https://formatjs.buildbuddy.io/invocation/609bfdab-4826-4b87-8536-a3322406bfc6)
passed in 51.183 seconds with nine tracked executions, 4.692 CPU seconds,
407,064,576-byte maximum action peak memory, 703,150,086 input download bytes and
7,492,233 output upload bytes. Earlier attempts and concurrent builds populated
caches. These workspace-specific observations prove passing behavior and record
resources; they do not establish a cold baseline or speedup.

## Compositor profile baseline

The [35dcc40 source workflow](https://formatjs.buildbuddy.io/invocation/d00e04bc-bdc4-4c55-865c-765b54c905ab)
and [BCR consumer](https://formatjs.buildbuddy.io/invocation/50d7daa2-1f3d-4806-9e53-2201eeadddac)
passed with the 6,341-unit source/object profile. BB now saves separate graphics,
aggregate, full-suite and consumer traces. The collector verifies artifact digests
and exports fixed timing categories and action mnemonics.

| Phase | Trace span (s) | Critical path (s) | Cache checks, cumulative (s) |
| --- | ---: | ---: | ---: |
| Initial graphics check | 63.629 | 1.216 | 3.748 |
| Source aggregate | 10.395 | 0.363 | 0.515 |
| Full source suite | 4.096 | 0.422 | 2.039 |
| Independent BCR consumer | 48.389 | 1.960 | 1.105 |

Cumulative categories overlap and are not elapsed phase times. These runs reuse
caches; they establish neither a cold baseline nor a controlled speedup. The
initial command and independent consumer cost much more than their action
critical paths. Measure frontend/driver overhead before changing source coverage
or compiler configuration. Earlier 164.160-second aggregate observations lack
comparable traces and cannot establish the cause of that difference.

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

## Blink Rust prerequisite observation

[d158dbb source aggregate](https://formatjs.buildbuddy.io/invocation/4defb7b1-866f-45d2-aaf4-6d527ce26aae)
passed in 9.648 seconds with two tracked remote actions, 0.121 CPU seconds,
113,438,720 bytes maximum action peak memory, 1,702,908 input bytes and 7,121
output bytes. The following [full source suite](https://formatjs.buildbuddy.io/invocation/21b5cd25-eeef-43ae-9a1f-13d19fc7add5)
passed in 3.737 seconds with zero tracked remote actions, including font-format
and original mixed-language panic probes. Its independent BCR source suite took
39.841 seconds with 12 tracked actions and 2.445 CPU seconds. These incremental
observations reuse caches and do not establish a controlled speedup.

## Blink generator header dependencies

The [d8f41f0 BCR source suite](https://formatjs.buildbuddy.io/invocation/355edf5f-4bd3-4c6c-aeb2-6a75278992d8)
passed in 461.492 seconds with 3,254 tracked actions, 3,781.265 CPU seconds,
1,146,408,960 bytes maximum action peak memory and 3,321,451,213 worker input
bytes. This is an incremental observation, not a controlled timing comparison.

The shared compilation header list included new auxiliary testing headers.
`3888599` instead selects generator headers through native C/C++ dependency
owners, retaining the exact pre-IDL header set. This removes those unrelated
inputs from existing compile actions. Timing impact remains unmeasured; the
expanded generator pipeline adds work of its own.

The [3888599 source aggregate](https://formatjs.buildbuddy.io/invocation/0d383fd0-cb6b-4a40-92cf-c819f0f5cbd6)
passed in 13.056 seconds with 33 tracked remote actions and 29.160 CPU seconds.
Its verified profile records 26 ElectronPython actions, 15 CppCompile actions
and one CppLink action. Generator cumulative time was 43.995 seconds; critical
path was 7.799 seconds. The following [full suite](https://formatjs.buildbuddy.io/invocation/879a5861-748a-484b-8022-239e259bd320)
passed in 3.904 seconds with zero tracked remote actions. The independent BCR
suite took 53.371 seconds with zero tracked remote actions. These runs reuse
caches and build different generator sets; they do not establish a controlled
speedup over the earlier observation.

## Platform-specific example inputs

The desktop example now includes `macos-update-smoke.cjs` only on macOS. A
before/after `aquery` of the Linux assembly action confirmed that its declared
inputs stop containing that file; both queries executed zero build actions.
Future Mac-only smoke edits therefore avoid invalidating Linux/Windows app and
installer actions. Elapsed-time savings remain unmeasured.

BB checks the full cross-build's actual action dependency sets and generated
assembly manifests with [the input audit](../tools/ci/platform_inputs_audit.py).
The Mac script must be packaged and declared only for macOS; an empty query or
missing OS family fails the gate.

The [36047d3 BB cross-build](https://formatjs.buildbuddy.io/invocation/6e4b1d4b-8b35-48d5-9545-f508a9eea137)
passed the real audit for four Linux, two macOS and ten Windows app actions.
[All four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42699997515)
also passed after input pruning.

The [Mac ZIP differential gate](updates.md) separately measured 486,177 payload
bytes downloaded from a 285,561,263-byte ZIP: 99.83% reuse. This assumes an
existing v1 ZIP cache and excludes blockmap metadata transfer.


## Source runtime dependency audit

The [36047d3 source workflow](https://formatjs.buildbuddy.io/invocation/19e5a281-f4fc-4dc9-a9bb-7afd63f9b036)
spent 79.542 and 82.871 seconds on separate bootstrap/source runtime dependency
queries: 162.413 seconds total. It reached the hosted one-hour deadline with
74,197 action-cache hits, 1,185 misses and 1,166 uploads. Compilation cache work
survived the deadline; this was not a compiler failure.

`da21d47` shares one dependency graph traversal, still rejecting the Linux
bootstrap runtime and requiring the source runtime. Its
[combined cquery](https://formatjs.buildbuddy.io/invocation/0af9c31f-eb3b-44af-823c-521c96c18016)
passed in 75.772 seconds before the full source build continued. These are
mixed-cache phase observations with different example inputs. They establish
one fewer query and an observed shorter audit phase, not a cold-build or
end-to-end speedup. Full source desktop execution remains unverified.

The next [source run](https://formatjs.buildbuddy.io/invocation/84bae3f9-8f35-4145-891a-5b659ed6dac9)
also reached the hosted one-hour deadline, at 3,600.537 seconds, without a compiler
error. Its full-build child recorded 74,517 action-cache hits, 202 misses and 202
uploads. Different work sets and cache populations prevent a speedup claim;
full source desktop execution remains unverified.

The [69c3287 source retry](https://formatjs.buildbuddy.io/invocation/ea3d383e-64bd-494f-ac86-1e566abfd4a5)
reached the same hosted limit at 3,600.472 seconds. Its full-build child recorded
73,917 hits, 1,970 misses and 1,922 uploads. Its 917 observed compilation groups
shared no normalized target/output group with the previous run's executed
compilations. This establishes new compilation work retained in cache, not a
completed source desktop build or a timing improvement.
