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

## Next measurements

The [33244d8 matrix](https://formatjs.buildbuddy.io/invocation/2862db5f-beee-4568-bb0e-0ba735d29433)
produced a 1,676,779,799-byte smoke ZIP, verified before GH handoff. Four native
hosts each download that full archive: roughly 6.71 GB of archive payload across
those hosts, excluding the bridge and protocol overhead. All four
[native jobs passed](https://github.com/formatjs/rules_electron/actions/runs/42352517657),
including the public macOS release ZIP. Build host-specific transport shards on
BB next; preserve all seven architecture checks, exact installer bytes and both
Windows compiler variants. Linux ARM64 must remain cross-built and checked even
without a native consumer.

Repeat the same target set and product inputs with explicit cold/warm cache
conditions. Record workflow and child build durations, analysis time, actual
executed/cache-hit counts, executor CPU/peak memory and transfer bytes. Keep
fixture and desktop workspaces separate in reports.

The smoke archive duplicates runtime bytes across unpacked apps, DEBs and Windows
compiler variants. Measure execution
time and transferred bytes before changing compression or transport layout;
preserve every target, exact installer bytes, symlink/mode metadata and native
coverage. Source-runtime compilation needs its own baseline once the complete
runtime links.
