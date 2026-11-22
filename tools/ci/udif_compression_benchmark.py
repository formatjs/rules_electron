"""Compare bounded parallel UDIF compression with its serial upstream reference."""

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from python.runfiles import runfiles


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size-mib", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.size_mib <= 1024 or not 1 <= args.repeats <= 10:
        parser.error("Expected 1–1024 MiB and 1–10 repeats")
    files = runfiles.Create()
    tools = {name: files.Rlocation(repository + "/dmg") for name, repository in
             [("serial", "udif_reference_sources"), ("parallel", "udif_sources")]}
    if any(not path or not Path(path).is_file() for path in tools.values()):
        raise ValueError("Missing declared converter runfiles")
    timings = {name: [] for name in tools}
    expected = None
    with tempfile.TemporaryDirectory(prefix="udif-benchmark-") as temporary:
        root = Path(temporary)
        source, output = root / "filesystem.iso", root / "image.dmg"
        noise = random.Random(0).randbytes(256 * 1024)
        blocks = [bytes(256 * 1024), noise, bytes(range(256)) * 1024, noise[:128 * 1024] + bytes(128 * 1024)]
        with source.open("wb") as content:
            for i in range(args.size_mib * 4):
                content.write(blocks[i % len(blocks)])
        for _ in range(args.repeats):
            for name, converter in tools.items():
                started = time.monotonic()
                subprocess.run([converter, str(source), str(output)], check=True, capture_output=True)
                timings[name].append(time.monotonic() - started)
                with output.open("rb") as content:
                    digest = hashlib.file_digest(content, "sha256").hexdigest()
                if expected is not None and digest != expected:
                    raise ValueError("Serial and parallel converter bytes differ")
                expected = digest
        result = {"input_bytes": source.stat().st_size, "output_bytes": output.stat().st_size,
                  "sha256": expected, "cpu_count": os.cpu_count(), "seconds": timings,
                  "median_seconds": {name: statistics.median(values) for name, values in timings.items()}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
