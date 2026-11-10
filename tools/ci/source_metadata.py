"""Fetch data-only ARM64 capture artifacts from one successful overlay build."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import urllib.parse

try:
    from .buildbuddy_artifacts import api_request, invocation_id
except ImportError:
    from buildbuddy_artifacts import api_request, invocation_id


ARTIFACTS = {
    'linux-arm64-graph.json.gz': 64 * 1024**2,
    'linux-arm64-graph.json.summary.json': 4 * 1024**2,
    'capture-inputs.json': 1024**2,
    'fuses_flags.bzl': 1024**2,
    'metadata-tools-MODULE.bazel.lock': 16 * 1024**2,
    'source-capture-MODULE.bazel.lock': 16 * 1024**2,
    'linux-arm64-perfetto-target.json': 16 * 1024**2,
    'linux-arm64-perfetto-execution.json': 16 * 1024**2,
    'linux-arm64-perfetto-snapshot.json': 16 * 1024**2,
    'linux-arm64-v8-support-target.json': 16 * 1024**2,
    'linux-arm64-v8-support-execution.json': 16 * 1024**2,
    'linux-arm64-v8-support-snapshot.json': 16 * 1024**2,
    'linux-arm64-protobuf-target.json': 16 * 1024**2,
    'linux-arm64-protobuf-execution.json': 16 * 1024**2,
    'linux-arm64-protobuf-snapshot.json': 16 * 1024**2,
}


def artifacts(response, sha):
    values = response.get('invocation', [])
    if len(values) != 1:
        raise ValueError('Expected one metadata capture')
    invocation = values[0]
    if (not re.fullmatch(r'[0-9a-f]{40}', sha) or invocation.get('commitSha') != sha
            or invocation.get('repoUrl', '').removesuffix('.git') != 'https://github.com/formatjs/electron'
            or invocation.get('pattern') != 'Capture Linux ARM64 GN metadata'
            or invocation.get('invocationStatus') != 'COMPLETE_INVOCATION_STATUS' or not invocation.get('success')):
        raise ValueError('Expected exact successful overlay metadata capture')
    result = {}
    for name, limit in ARTIFACTS.items():
        matches = [item for item in invocation.get('artifacts', []) if PurePosixPath(item.get('name', '')).name == name]
        if len(matches) != 1:
            raise ValueError('Expected one capture artifact')
        uri = matches[0].get('uri', '')
        parsed = urllib.parse.urlsplit(uri)
        digest = re.search(r'/blobs/([0-9a-f]{64})/(\d+)$', parsed.path)
        if (parsed.scheme != 'bytestream' or parsed.netloc not in ('formatjs.buildbuddy.io', 'remote.buildbuddy.io')
                or not digest or int(digest[2]) > limit):
            raise ValueError('Invalid capture artifact store or size')
        result[name] = (uri, digest[1], int(digest[2]))
    return result


def download(response, sha, key, directory):
    records = artifacts(response, sha)
    directory.mkdir(parents=True, exist_ok=False)
    for name, (uri, digest, size) in records.items():
        temporary = directory / (name + '.part')
        hasher, received = hashlib.sha256(), 0
        with api_request('GetFile', {'uri': uri}, key) as source, temporary.open('xb') as destination:
            while block := source.read(min(1024**2, size - received + 1)):
                received += len(block)
                if received > size:
                    raise ValueError('Capture artifact exceeds declared size')
                hasher.update(block)
                destination.write(block)
        if received != size or hasher.hexdigest() != digest:
            raise ValueError('Capture artifact digest or size mismatch')
        temporary.rename(directory / name)
    validate_profiles(directory)
    return sum(record[2] for record in records.values())


def validate_profiles(directory):
    with (directory / 'linux-arm64-graph.json.gz').open('rb') as stream:
        graph_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    for module in ('perfetto', 'v8-support', 'protobuf'):
        for role in ('target', 'execution', 'snapshot'):
            profile = json.loads((directory / ('linux-arm64-' + module + '-' + role + '.json')).read_bytes())
            if (profile.get('target_arch') != 'arm64' or profile.get('role') != role
                    or profile.get('graph_sha256') != graph_digest):
                raise ValueError('Capture profile graph or role mismatch')
            libraries = profile.get('libraries')
            if not isinstance(libraries, dict) or not libraries:
                raise ValueError('Missing capture profile libraries')
            architectures = {record['architecture'] for record in libraries.values()}
            expected = 'arm64' if role == 'target' else 'x64'
            allowed = {'arm64', 'x64'} if module == 'perfetto' and role == 'target' else {expected}
            if expected not in architectures or architectures - allowed:
                raise ValueError('Capture profile compiler architecture mismatch')
            if module != 'v8-support':
                bare = '//third_party/perfetto:libperfetto' if module == 'perfetto' else '//third_party/protobuf:' + ('protoc' if role == 'execution' else 'protobuf_lite')
                suffix = '' if role == 'target' else '(//build/toolchain/linux:' + ('clang_x64' if role == 'execution' else 'clang_x64_v8_arm64') + ')'
                if profile.get('root') != bare + suffix:
                    raise ValueError('Capture profile root mismatch')


def main():
    try:
        key, sha = os.environ['BUILDBUDDY_API_KEY'], os.environ['BUILD_SHA']
        if not key or not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('Invalid capture identity')
        identifier = invocation_id(os.environ['INVOCATION_URL'])
        with api_request('GetInvocation', {'selector': {'invocation_id': identifier}, 'include_artifacts': True}, key) as response:
            data = response.read(16 * 1024**2 + 1)
        if len(data) > 16 * 1024**2:
            raise ValueError('Capture metadata exceeds limit')
        size = download(json.loads(data), sha, key, Path('artifacts/electron-linux-arm64-metadata'))
    except Exception:
        print('SOURCE_METADATA_HANDOFF_FAILED', file=sys.stderr)
        return 1
    print('SOURCE_METADATA_VERIFIED bytes=' + str(size))
    return 0


if __name__ == '__main__':
    sys.exit(main())
