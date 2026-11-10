"""Resolve smoke status scope from one verified BB build, including manual runs."""

import json
import os
import re
import sys

try:
    from .buildbuddy_artifacts import api_request, invocation_id, smoke_status_context
except ImportError:
    from buildbuddy_artifacts import api_request, invocation_id, smoke_status_context


def main():
    try:
        key, sha = os.environ['BUILDBUDDY_API_KEY'], os.environ['BUILD_SHA']
        if not key or not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('Invalid smoke identity')
        identifier = invocation_id(os.environ['INVOCATION_URL'])
        with api_request('GetInvocation', {'selector': {'invocation_id': identifier}}, key) as response:
            data = response.read(8 * 1024**2 + 1)
        if len(data) > 8 * 1024**2:
            raise ValueError('Invocation metadata exceeds limit')
        context = smoke_status_context(json.loads(data), sha)
    except Exception:
        print('SMOKE_STATUS_CONTEXT_FAILED', file=sys.stderr)
        return 1
    print(context)
    return 0


if __name__ == '__main__':
    sys.exit(main())
