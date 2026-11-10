"""Publish verified feeds with explicit S3 SigV4 credentials and conditional writes."""

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request

from electron.tools.publish_update import Publisher, snapshot


def signed_headers(method, url, headers, payload_hash, access_key, secret_key, region, timestamp, session_token=None):
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise ValueError('S3 publication does not use query parameters')
    result = {name.lower(): ' '.join(value.split()) for name, value in headers.items()}
    result.update({'host': parts.netloc.lower(), 'x-amz-date': timestamp,
                   'x-amz-content-sha256': payload_hash})
    if session_token is not None:
        result['x-amz-security-token'] = session_token
    names = ';'.join(sorted(result))
    canonical_headers = ''.join(name + ':' + result[name] + '\n' for name in sorted(result))
    # S3 keys retain repeated slashes; never normalize their paths.
    uri = quote(unquote(parts.path, errors='strict'), safe='/-._~') or '/'
    canonical = '\n'.join([method, uri, '', canonical_headers, names, payload_hash])
    date = timestamp[:8]
    scope = date + '/' + region + '/s3/aws4_request'
    to_sign = '\n'.join(['AWS4-HMAC-SHA256', timestamp, scope,
                         hashlib.sha256(canonical.encode()).hexdigest()])
    key = ('AWS4' + secret_key).encode()
    for value in (date, region, 's3', 'aws4_request'):
        key = hmac.digest(key, value.encode(), 'sha256')
    signature = hmac.new(key, to_sign.encode(), 'sha256').hexdigest()
    result['authorization'] = ('AWS4-HMAC-SHA256 Credential=' + access_key + '/' + scope
                               + ',SignedHeaders=' + names + ',Signature=' + signature)
    return result


class S3Publisher(Publisher):
    def __init__(self, destination, region, access_key, secret_key, session_token=None, allow_http_loopback=False):
        super().__init__(destination, allow_http_loopback=allow_http_loopback)
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', region):
            raise ValueError('Explicit S3 region required')
        if not isinstance(access_key, str) or not re.fullmatch(r'[A-Za-z0-9]+', access_key):
            raise ValueError('Invalid S3 access key')
        for value in (secret_key, session_token):
            if value is not None and (not value or any(not 33 <= ord(c) <= 126 for c in value)):
                raise ValueError('Invalid S3 credential')
        if secret_key is None:
            raise ValueError('S3 secret key required')
        parts = urlsplit(self.destination)
        self.destination = urlunsplit((parts.scheme, parts.netloc,
                                       quote(unquote(parts.path, errors='strict'), safe='/-._~'), '', ''))
        self.region, self.access_key, self.secret_key, self.session_token = region, access_key, secret_key, session_token

    def request(self, method, name, data=None, headers=None):
        if method not in ('HEAD', 'GET', 'PUT'):
            raise ValueError('Unsupported S3 publication method')
        payload_hash = hashlib.sha256(b'').hexdigest()
        if data is not None:
            position = data.tell()
            payload_hash = hashlib.file_digest(data, 'sha256').hexdigest()
            data.seek(position)
        url = self.destination + quote(name, safe='-._~')
        headers = signed_headers(method, url, headers or {}, payload_hash,
                                 self.access_key, self.secret_key, self.region,
                                 datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'), self.session_token)
        request = Request(url, data=data, headers=headers, method=method)
        try:
            return self.opener.open(request, timeout=60)
        except HTTPError as error:
            return error

    def publish(self, output, channel, uploads):
        if any(path.stat().st_size > 5 * 1024**3 for path in [*uploads, output / channel]):
            raise ValueError('S3 single-part upload exceeds 5 GiB')
        return super().publish(output, channel, uploads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--channel', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--access-key-env', default='AWS_ACCESS_KEY_ID')
    parser.add_argument('--secret-key-env', default='AWS_SECRET_ACCESS_KEY')
    parser.add_argument('--session-token-env', default='AWS_SESSION_TOKEN')
    parser.add_argument('--allow-http-loopback', action='store_true')
    args = parser.parse_args()
    try:
        publisher = S3Publisher(args.destination, args.region, os.environ[args.access_key_env],
                                os.environ[args.secret_key_env], os.environ.get(args.session_token_env),
                                args.allow_http_loopback)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            uploads = snapshot(args.feed, args.channel, output)
            publisher.publish(output, args.channel, uploads)
        print('S3_UPDATE_PUBLISHED')
    except Exception:
        # Service errors may contain credentials or signed URLs.
        print('S3_UPDATE_PUBLICATION_FAILED', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
