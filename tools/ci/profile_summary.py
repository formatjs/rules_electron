"""Summarize Bazel Chrome traces without exposing command arguments or paths."""

from collections import defaultdict
import gzip
import io
import json
import math
import codecs
import zlib


def summarize_source(profile, allow_invalid_timings=False):
    categories = {
        "action processing", "remote action cache check", "remote output download",
        "general information", "skyframe evaluator", "critical path component",
        "thread wait", "VFS read", "Fetching repository",
        "action dependency checking", "action resource lock", "update action information",
        "complete action execution", "discover inputs", "remote action execution",
        "Local parse to prepare for remote execution", "Remote execution upload time",
        "Remote execution process wall time", "Remote execution queuing time",
        "Remote execution setup", "Remote execution file fetching", "remote network",
        "VFS stat", "VFS readdir", "VFS readlink", "VFS md5", "VFS xattr", "VFS open",
        "filesystem traversal", "Staging per-action file system", "gc notification",
    }
    mnemonics = {
        "CppCompile", "CppLink", "CppArchive", "Rustc", "RustBindgen",
        "CargoBuildScriptRun", "CargoBuildScriptCompile", "ElectronPython", "FileWrite",
    }
    phases = {"runAnalysisPhase", "runLoadingPhase", "evaluateTargetPatterns", "runExecutorMainPhase"}
    operations = {'MerkleTreeComputer.buildForSpawn', 'MerkleTreeComputer.buildForFiles', 'acquiring semaphore'}
    events = []
    discarded = defaultdict(int)
    for event in profile["traceEvents"]:
        args = event.get("args", {})
        if event.get("ph") == "M" and event.get("name") == "thread_name" and args.get("name") == "Critical Path":
            events.append({"ph": "M", "name": "thread_name", "pid": event.get("pid"), "tid": event.get("tid"), "args": {"name": "Critical Path"}})
        if event.get("ph") != "X":
            continue
        timestamp, duration = event.get("ts"), event.get("dur")
        problem = None
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in [timestamp, duration]):
            problem = 'NON_FINITE'
        elif abs(timestamp) > 2**63 or not 0 <= duration <= 7 * 86400 * 1000000:
            problem = 'OUT_OF_RANGE'
        elif allow_invalid_timings and abs(timestamp) > 7 * 86400 * 1000000:
            problem = 'OUT_OF_RANGE'
        if problem:
            if not allow_invalid_timings:
                raise ValueError("Invalid source profile timing" if problem == 'NON_FINITE' else "Source profile timing exceeds limits")
            discarded[problem] += 1
            continue
        mnemonic = args.get("mnemonic")
        events.append({
            "ph": "X", "pid": event.get("pid"), "tid": event.get("tid"),
            "ts": timestamp, "dur": duration,
            "cat": event.get("cat") if event.get("cat") in categories else "other",
            "name": event.get("name") if event.get("name") in phases | operations else "",
            "args": {"mnemonic": mnemonic if mnemonic in mnemonics else "other"} if mnemonic else {},
        })
    result = summarize({"traceEvents": events})
    if discarded:
        result['discarded_timing_events'] = dict(discarded)
    result['operations'] = {}
    for name in sorted(operations):
        durations = [event['dur'] / 1000000 for event in events if event.get('ph') == 'X' and event.get('name') == name]
        if durations:
            result['operations'][name] = {'count': len(durations), 'cumulative_seconds': round(sum(durations), 3),
                                          'max_seconds': round(max(durations), 3)}
    if not 0 <= result["trace_span_seconds"] <= 7 * 86400:
        raise ValueError("Source profile span exceeds limits")
    return result


def decode_profile(data, limit=128 * 1024**2):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
        decoded = compressed.read(limit + 1)
    if len(decoded) > limit:
        raise ValueError("Profile exceeds expanded size limit")
    return json.loads(decoded)


def recover_source_profile(data, limit=128 * 1024**2):
    inflater = zlib.decompressobj(31)
    decoded = inflater.decompress(data, limit + 1)
    if len(decoded) > limit:
        raise ValueError('Profile exceeds expanded size limit')
    if inflater.eof:
        raise ValueError('Recovery requires a truncated gzip stream')
    text = codecs.getincrementaldecoder('utf-8')().decode(decoded, final=False)
    decoder = json.JSONDecoder()
    position = 0

    def skip_space():
        nonlocal position
        while position < len(text) and text[position] in ' \r\n\t':
            position += 1

    def consume(token):
        nonlocal position
        skip_space()
        if not text.startswith(token, position):
            raise ValueError('Invalid source profile prefix')
        position += len(token)

    consume('{')
    while True:
        skip_space()
        key, position = decoder.raw_decode(text, position)
        if not isinstance(key, str):
            raise ValueError('Invalid source profile key')
        consume(':')
        if key == 'traceEvents':
            break
        skip_space()
        _, position = decoder.raw_decode(text, position)
        consume(',')
    consume('[')
    events = []
    while True:
        skip_space()
        if position >= len(text) or text[position] == ']':
            break
        try:
            event, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            break
        if not isinstance(event, dict):
            raise ValueError('Invalid source profile event')
        events.append(event)
        skip_space()
        if position >= len(text) or text[position] == ']':
            break
        consume(',')
    if not events:
        raise ValueError('Source profile contains no recoverable events')
    return {'traceEvents': events}


def summarize(profile):
    events = profile["traceEvents"]
    critical_threads = {(e.get("pid"), e.get("tid")) for e in events
                        if e.get("ph") == "M" and e.get("name") == "thread_name"
                        and e.get("args", {}).get("name") == "Critical Path"}
    categories = defaultdict(lambda: {"count": 0, "cumulative_seconds": 0})
    complete = [e for e in events if e.get("ph") == "X"
                and isinstance(e.get("dur"), (int, float)) and isinstance(e.get("ts"), (int, float))]
    if not complete:
        raise ValueError("Profile contains no complete timing events")
    actions = defaultdict(lambda: {"count": 0, "cumulative_seconds": 0, "max_seconds": 0})
    critical = 0
    for event in complete:
        duration = event["dur"] / 1000000
        category = categories[event.get("cat", "uncategorized")]
        category["count"] += 1
        category["cumulative_seconds"] += duration
        if (event.get("pid"), event.get("tid")) in critical_threads:
            critical += duration
        mnemonic = event.get("args", {}).get("mnemonic")
        if event.get("cat") == "action processing" and mnemonic:
            action = actions[mnemonic]
            action["count"] += 1
            action["cumulative_seconds"] += duration
            action["max_seconds"] = max(action["max_seconds"], duration)
    def rounded(values):
        return {key: round(value, 3) if isinstance(value, float) else value for key, value in values.items()}
    result = {
        "trace_span_seconds": round((max(e["ts"] + e["dur"] for e in complete) - min(e["ts"] for e in complete)) / 1000000, 3),
        "categories": {key: rounded(value) for key, value in sorted(categories.items(), key=lambda p: -p[1]["cumulative_seconds"])[:20]},
        "actions": {key: rounded(value) for key, value in sorted(actions.items(), key=lambda p: -p[1]["max_seconds"])[:15]},
        "phases_seconds": {name: round(sum(e["dur"] for e in complete if e.get("name") == name) / 1000000, 3)
                           for name in ["runAnalysisPhase", "runLoadingPhase", "evaluateTargetPatterns", "runExecutorMainPhase"]
                           if any(e.get("name") == name for e in complete)},
    }
    if critical_threads:
        result["critical_path_seconds"] = round(critical, 3)
    return result
