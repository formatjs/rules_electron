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

## Next measurements

Repeat the same target set and product inputs with explicit cold/warm cache
conditions. Record workflow and child build durations, analysis time, actual
executed/cache-hit counts, executor CPU/peak memory and transfer bytes. Keep
fixture and desktop workspaces separate in reports.

The smoke archive duplicates runtime bytes across unpacked apps, DEBs and Windows
compiler variants. It also recompresses existing ZIP/DEB files. Measure execution
time and transferred bytes before changing compression or transport layout;
preserve every target, exact installer bytes, symlink/mode metadata and native
coverage. Source-runtime compilation needs its own baseline once the complete
runtime links.
