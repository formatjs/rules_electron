"""Sample only numeric Bazel-server counters; keep deadline-safe JSONL prefixes."""

import argparse
import json
import os
from pathlib import Path
import time

NAME = 'source-frontend-metrics.jsonl'
LIMIT = 1024**2
FIELDS = {'elapsed_seconds', 'cpu_cores', 'rss_bytes', 'threads', 'minor_faults', 'major_faults'}


def parse_stat(text, page_size):
    fields = text[text.rindex(')') + 2:].split()
    result = {
        'cpu_ticks': int(fields[11]) + int(fields[12]), 'start_ticks': int(fields[19]),
        'rss_bytes': int(fields[21]) * page_size, 'threads': int(fields[17]),
        'minor_faults': int(fields[7]), 'major_faults': int(fields[9]),
    }
    if any(value < 0 for value in result.values()):
        raise ValueError('Invalid process counters')
    return result


def read_process(pid, page_size):
    return parse_stat(Path('/proc/' + str(pid) + '/stat').read_text(), page_size)


def collect(pid, output, interval=5, max_samples=1440):
    page_size, ticks = os.sysconf('SC_PAGE_SIZE'), os.sysconf('SC_CLK_TCK')
    previous = read_process(pid, page_size)
    started = previous_time = time.monotonic()
    count = 0
    with Path(output).open('w', buffering=1) as destination:
        for _ in range(max_samples):
            time.sleep(interval)
            try:
                current = read_process(pid, page_size)
            except (FileNotFoundError, ProcessLookupError):
                break
            if current['start_ticks'] != previous['start_ticks']:
                break
            now = time.monotonic()
            elapsed = now - previous_time
            if elapsed <= 0 or any(current[key] < previous[key] for key in ('cpu_ticks', 'minor_faults', 'major_faults')):
                raise ValueError('Invalid process counter interval')
            sample = {
                'elapsed_seconds': round(now - started, 6),
                'cpu_cores': round((current['cpu_ticks'] - previous['cpu_ticks']) / ticks / elapsed, 9),
                'rss_bytes': current['rss_bytes'], 'threads': current['threads'],
                'minor_faults': current['minor_faults'] - previous['minor_faults'],
                'major_faults': current['major_faults'] - previous['major_faults'],
            }
            destination.write(json.dumps(sample, separators=(',', ':')) + '\n')
            previous, previous_time = current, now
            count += 1
    return count


def summarize(data):
    if len(data) > LIMIT:
        raise ValueError('Frontend metrics exceed size limit')
    lines = data.splitlines()
    trailing = bool(data and not data.endswith(b'\n'))
    if trailing:
        lines = lines[:-1]
    if not lines or len(lines) > 4096:
        raise ValueError('Invalid frontend sample count')
    samples = []
    elapsed, cpu = 0, 0
    for line in lines:
        sample = json.loads(line)
        if not isinstance(sample, dict) or set(sample) != FIELDS:
            raise ValueError('Invalid frontend metric fields')
        if (any(type(sample[key]) not in (int, float) for key in ('elapsed_seconds', 'cpu_cores'))
                or not elapsed < sample['elapsed_seconds'] <= 7 * 86400 or not 0 <= sample['cpu_cores'] <= 65536
                or any(type(sample[key]) is not int or not 0 <= sample[key] < 2**63 for key in FIELDS - {'elapsed_seconds', 'cpu_cores'})):
            raise ValueError('Invalid frontend metric value')
        cpu += sample['cpu_cores'] * (sample['elapsed_seconds'] - elapsed)
        elapsed = sample['elapsed_seconds']
        samples.append(sample)
    return {
        'samples': len(samples), 'recorded_seconds': round(elapsed, 3),
        'sampled_cpu_seconds': round(cpu, 3), 'average_cpu_cores': round(cpu / elapsed, 3),
        'max_cpu_cores': round(max(sample['cpu_cores'] for sample in samples), 3),
        'sampled_peak_rss_bytes': max(sample['rss_bytes'] for sample in samples),
        'max_threads': max(sample['threads'] for sample in samples),
        'minor_faults': sum(sample['minor_faults'] for sample in samples),
        'major_faults': sum(sample['major_faults'] for sample in samples),
        'discarded_trailing_record': int(trailing),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.pid <= 0:
            raise ValueError('Invalid process ID')
        count = collect(args.pid, args.output)
        print('SOURCE_FRONTEND_METRICS_FINISHED samples=' + str(count))
    except (OSError, ValueError, IndexError):
        print('SOURCE_FRONTEND_METRICS_UNAVAILABLE')


if __name__ == '__main__':
    main()
