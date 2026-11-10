"""Independent SigV4 verification for release socket tests."""

from datetime import datetime, timezone
import hashlib
import hmac
import re
from urllib.parse import parse_qs, parse_qsl, quote, urlsplit

ACCESS = 'FIXTUREACCESSKEY'
SECRET = 'fixture/secret+key='
TOKEN = 'fixture/session+token='
PREFIX = '/bucket/release%20prefix//'


def authorized(request, body):
    match = re.fullmatch(r'AWS4-HMAC-SHA256 Credential=' + ACCESS
                        + r'/(\d{8})/us-west-2/s3/aws4_request,SignedHeaders=([^,]+),Signature=([0-9a-f]{64})',
                        request.headers.get('Authorization', ''))
    if not match:
        return False
    date, signed, signature = match.groups()
    names = signed.split(';')
    url = urlsplit(request.path)
    query = parse_qs(url.query, keep_blank_values=True)
    required = {'host', 'x-amz-date', 'x-amz-content-sha256', 'x-amz-security-token'}
    if request.command == 'PUT' or request.command == 'POST' and 'uploadId' in query:
        required.update({'content-length', 'content-type'})
        if request.command != 'PUT' or 'uploadId' not in query:
            required.add('if-match' if request.headers.get('If-Match') else 'if-none-match')
    if names != sorted(set(names)) or not required.issubset(names):
        return False
    timestamp = request.headers['x-amz-date']
    if (timestamp[:8] != date or request.headers['x-amz-security-token'] != TOKEN
            or request.headers['x-amz-content-sha256'] != hashlib.sha256(body).hexdigest()
            or abs((datetime.now(timezone.utc) - datetime.strptime(timestamp, '%Y%m%dT%H%M%SZ')
                    .replace(tzinfo=timezone.utc)).total_seconds()) > 120):
        return False
    canonical_query = '&'.join(key + '=' + value for key, value in sorted(
        (quote(key, safe='-._~'), quote(value, safe='-._~')) for key, value in parse_qsl(url.query, keep_blank_values=True)))
    canonical = request.command + '\n' + url.path + '\n' + canonical_query + '\n'
    canonical += ''.join(name + ':' + ' '.join(request.headers[name].split()) + '\n' for name in names)
    canonical += '\n' + signed + '\n' + hashlib.sha256(body).hexdigest()
    scope = date + '/us-west-2/s3/aws4_request'
    message = 'AWS4-HMAC-SHA256\n' + timestamp + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()
    key = ('AWS4' + SECRET).encode()
    for part in [date, 'us-west-2', 's3', 'aws4_request']:
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(signature, hmac.new(key, message.encode(), hashlib.sha256).hexdigest())
