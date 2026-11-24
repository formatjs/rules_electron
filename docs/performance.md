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

The prebuilt sample benchmark builds `examples/desktop//:cross_build_smoke_bundle`
for all seven variants using the pinned Electron runtime. On
benchmark commit `fcf00ef`, Electron packaging actions and `MakeDeb` carry
`no-cache`; compiler and tool caches remain enabled. The named Bazel config
`prebuilt-packaging-benchmark` repeats that mode on BB; normal CI keeps caching.
This measures packaging
work with prebuilt Chromium/Node runtime binaries. It does not claim a cold
toolchain build or complete electron-builder feature parity.

The [packaging rebuild](https://formatjs.buildbuddy.io/invocation/de0a47f6-d0e5-40b1-9099-9937ffa54e7f)
took 186.442 seconds and executed 247 remote actions. The
[cached matrix](https://formatjs.buildbuddy.io/invocation/a5dc8f62-4087-4c4f-96f2-554444487402)
took 47.147 seconds. All four smoke archives matched byte-for-byte; the
[baseline native run](https://github.com/formatjs/rules_electron/actions/runs/42812973575)
passed Linux x64, macOS ARM64 and Windows x64/ARM64. This matrix includes
install/update fixtures, rather than one app and one installer.

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

## Next measurements

Repeat the same target set and product inputs with explicit cold/warm cache
conditions. Record workflow and child build durations, analysis time, actual
executed/cache-hit counts, executor CPU/peak memory and transfer bytes. Keep
fixture and desktop workspaces separate in reports.

The smoke archive duplicates runtime bytes across unpacked apps, DEBs and Windows
compiler variants. Measure execution
time and transferred bytes before changing compression or transport layout;
preserve every target, exact installer bytes, symlink/mode metadata and native
coverage. Electron runtime binaries remain prebuilt inputs in these comparisons.

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


## Runtime locale selection

The example already requested `en-US`, but macOS ZIP assembly previously ignored
that setting. Applying it to the main app and Electron framework `.lproj`
resources reduced the verified macOS smoke shard from 951,954,206 bytes at
`84c7f91` to 846,504,557 bytes at `bcd1dcf`: 105,449,649 bytes, or 11.08%.
The download jobs in [the baseline workflow](https://github.com/formatjs/rules_electron/actions/runs/42772882916)
and [the filtered workflow](https://github.com/formatjs/rules_electron/actions/runs/42773904346)
verified the BB artifact SHA and byte count. These are compressed smoke-shard
sizes containing several fixtures, not standalone app sizes or build speedups.
The [filtered BB suite](https://formatjs.buildbuddy.io/invocation/c5e15b8d-9636-4ac2-a7e5-297ff82c4e9c)
and [cross-build](https://formatjs.buildbuddy.io/invocation/c3f85091-78fd-4e63-8b36-8ac412a6d61e)
passed. [All four native hosts passed](https://github.com/formatjs/rules_electron/actions/runs/42773904346)
with locale selection; [the diagnostic follow-up](https://github.com/formatjs/rules_electron/actions/runs/42773969425)
also passed all four hosts. The macOS updater's final ZIP fell from 285,575,214
to 239,857,132 bytes (16.01%). Its real differential update fetched 446,182 bytes,
reusing 99.81% of the final archive. These fixtures use pinned prebuilt Electron.
