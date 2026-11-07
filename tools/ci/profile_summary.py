"""Summarize Bazel Chrome traces without exposing command arguments or paths."""

from collections import defaultdict
import gzip
import io
import json


def decode_profile(data, limit=128 * 1024**2):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
        decoded = compressed.read(limit + 1)
    if len(decoded) > limit:
        raise ValueError("Profile exceeds expanded size limit")
    return json.loads(decoded)


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
    }
    if critical_threads:
        result["critical_path_seconds"] = round(critical, 3)
    return result
