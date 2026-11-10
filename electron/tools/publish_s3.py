"""Publish verified feeds with explicit S3 SigV4 credentials and conditional writes."""

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import io
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request
from xml.etree import ElementTree as ET

from electron.tools.publish_update import Publisher, snapshot

MIN_PART = 5 * 1024**2
MAX_PART = 5 * 1024**3
MAX_OBJECT = 10000 * MAX_PART
XML_LIMIT = 1024**2


class FileSlice(io.RawIOBase):
    def __init__(self, source, offset, length):
        self.source, self.offset, self.length, self.position = source, offset, length, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (self.position if whence == 1 else self.length if whence == 2 else 0)
        if whence not in (0, 1, 2) or not 0 <= position <= self.length:
            raise ValueError('Invalid multipart slice position')
        self.position = position
        return position

    def readinto(self, buffer):
        self.source.seek(self.offset + self.position)
        count = self.source.readinto(memoryview(buffer)[:min(len(buffer), self.length - self.position)])
        if not count and self.position < self.length:
            raise ValueError('Truncated multipart source')
        self.position += count
        return count


def response_xml(response, expected):
    data = response.read(XML_LIMIT + 1)
    if len(data) > XML_LIMIT or b'<!' in data:
        raise ValueError('Invalid S3 XML response')
    root = ET.fromstring(data)
    if root.tag.rsplit('}', 1)[-1] != expected:
        raise ValueError('S3 operation did not complete')
    return root


def xml_field(root, name):
    values = [child.text for child in root if child.tag.rsplit('}', 1)[-1] == name]
    if len(values) != 1 or not values[0] or len(values[0]) > 2048:
        raise ValueError('Invalid S3 response field')
    return values[0]


def signed_headers(method, url, headers, payload_hash, access_key, secret_key, region, timestamp, session_token=None):
    parts = urlsplit(url)
    if parts.fragment:
        raise ValueError('S3 publication does not use fragments')
    result = {name.lower(): ' '.join(value.split()) for name, value in headers.items()}
    result.update({'host': parts.netloc.lower(), 'x-amz-date': timestamp,
                   'x-amz-content-sha256': payload_hash})
    if session_token is not None:
        result['x-amz-security-token'] = session_token
    names = ';'.join(sorted(result))
    canonical_headers = ''.join(name + ':' + result[name] + '\n' for name in sorted(result))
    # S3 keys retain repeated slashes; never normalize their paths.
    uri = quote(unquote(parts.path, errors='strict'), safe='/-._~') or '/'
    query = '&'.join(key + '=' + value for key, value in sorted(
        (quote(key, safe='-._~'), quote(value, safe='-._~'))
        for key, value in parse_qsl(parts.query, keep_blank_values=True, errors='strict', max_num_fields=32)))
    canonical = '\n'.join([method, uri, query, canonical_headers, names, payload_hash])
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
    def __init__(self, destination, region, access_key, secret_key, session_token=None, allow_http_loopback=False,
                 multipart_threshold=MAX_PART, part_size=64 * 1024**2):
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
        if not 1 <= multipart_threshold <= MAX_PART or not MIN_PART <= part_size <= MAX_PART:
            raise ValueError('Invalid S3 multipart sizes')
        self.multipart_threshold, self.part_size = multipart_threshold, part_size
        parts = urlsplit(destination if destination.endswith('/') else destination + '/')
        self.destination = urlunsplit((parts.scheme, parts.netloc,
                                       quote(unquote(parts.path, errors='strict'), safe='/-._~'), '', ''))
        self.region, self.access_key, self.secret_key, self.session_token = region, access_key, secret_key, session_token

    def request(self, method, name, data=None, headers=None, query=None):
        if method not in ('HEAD', 'GET', 'PUT', 'POST', 'DELETE'):
            raise ValueError('Unsupported S3 publication method')
        payload_hash = hashlib.sha256(b'').hexdigest()
        if data is not None:
            position = data.tell()
            payload_hash = hashlib.file_digest(data, 'sha256').hexdigest()
            data.seek(position)
        url = self.destination + quote(name, safe='-._~')
        if query:
            url += '?' + urlencode(query, quote_via=quote, safe='-._~')
        headers = signed_headers(method, url, headers or {}, payload_hash,
                                 self.access_key, self.secret_key, self.region,
                                 datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'), self.session_token)
        request = Request(url, data=data, headers=headers, method=method)
        try:
            return self.opener.open(request, timeout=60)
        except HTTPError as error:
            return error

    def put(self, path, condition):
        size = path.stat().st_size
        if size <= self.multipart_threshold:
            return super().put(path, condition)
        with self.request('POST', path.name, headers={'Content-Type': self.content_type(path)}, query={'uploads': ''}) as response:
            if response.status != 200:
                raise ValueError('S3 multipart initiation failed')
            upload_id = xml_field(response_xml(response, 'InitiateMultipartUploadResult'), 'UploadId')
        if any(not 33 <= ord(c) <= 126 for c in upload_id):
            raise ValueError('Invalid S3 upload identifier')
        completed = False
        try:
            body = ET.Element('CompleteMultipartUpload', xmlns='http://s3.amazonaws.com/doc/2006-03-01/')
            part_size = max(self.part_size, (size + 9999) // 10000)
            with path.open('rb') as source:
                for index, offset in enumerate(range(0, size, part_size), 1):
                    length = min(part_size, size - offset)
                    part = FileSlice(source, offset, length)
                    with self.request('PUT', path.name, part, {'Content-Length': str(length),
                                                              'Content-Type': 'application/octet-stream'},
                                      {'uploadId': upload_id, 'partNumber': str(index)}) as response:
                        if response.status != 200:
                            raise ValueError('S3 multipart part failed')
                        etag = response.headers.get('ETag', '')
                        if not re.fullmatch(r'"[\x21\x23-\x7e]{1,1024}"', etag):
                            raise ValueError('Invalid S3 part ETag')
                    entry = ET.SubElement(body, 'Part')
                    ET.SubElement(entry, 'PartNumber').text = str(index)
                    ET.SubElement(entry, 'ETag').text = etag
            data = ET.tostring(body, encoding='utf-8')
            with io.BytesIO(data) as source, self.request(
                    'POST', path.name, source, {**condition, 'Content-Length': str(len(data)),
                                               'Content-Type': 'application/xml'}, {'uploadId': upload_id}) as response:
                if response.status != 200:
                    return response.status
                result = response_xml(response, 'CompleteMultipartUploadResult')
                xml_field(result, 'ETag')
            completed = True
            return 200
        finally:
            if not completed:
                with self.request('DELETE', path.name, query={'uploadId': upload_id}) as response:
                    if response.status not in (200, 204, 404):
                        raise ValueError('S3 multipart cleanup failed')

    def publish(self, output, channel, uploads):
        if any(path.stat().st_size > MAX_OBJECT for path in [*uploads, output / channel]):
            raise ValueError('S3 multipart object exceeds part-count limit')
        return super().publish(output, channel, uploads)


def add_s3_arguments(parser):
    parser.add_argument('--destination', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--access-key-env', default='AWS_ACCESS_KEY_ID')
    parser.add_argument('--secret-key-env', default='AWS_SECRET_ACCESS_KEY')
    parser.add_argument('--session-token-env', default='AWS_SESSION_TOKEN')
    parser.add_argument('--allow-http-loopback', action='store_true')
    parser.add_argument('--multipart-threshold', type=int, default=MAX_PART, help='Bytes; defaults to 5 GiB.')
    parser.add_argument('--part-size', type=int, default=64 * 1024**2, help='Bytes; minimum 5 MiB.')


def publisher_from_environment(args, publisher_type=S3Publisher):
    return publisher_type(args.destination, args.region, os.environ[args.access_key_env],
                          os.environ[args.secret_key_env], os.environ.get(args.session_token_env),
                          args.allow_http_loopback, args.multipart_threshold, args.part_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--channel', required=True)
    add_s3_arguments(parser)
    args = parser.parse_args()
    try:
        publisher = publisher_from_environment(args)
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
