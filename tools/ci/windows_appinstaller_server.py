"""Serve immutable BB-built App Installer fixtures on native Windows hosts."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import re
from urllib.parse import urlsplit


class FixtureServer(ThreadingHTTPServer):
    def __init__(self, address, packages):
        self.packages, self.release = Path(packages), 'v1'
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != '/use-v2' or self.headers.get('Content-Length', '0') != '0':
            self.send_error(404)
            return
        self.server.release = 'v2'
        self.send_response(204)
        self.end_headers()

    def serve(self, head=False):
        path = urlsplit(self.path).path
        if path == '/ready':
            ready = b'MSIX_APPINSTALLER_READY'
            source, size, mime = io.BytesIO(ready), len(ready), 'text/plain'
        else:
            names = {'/desktop.appinstaller': ('msix_appinstaller_' + self.server.release + '.appinstaller', 'application/appinstaller')}
            names.update({'/appinstaller_signed_desktop_' + version + '.msix':
                          ('appinstaller_signed_desktop_' + version + '.msix', 'application/msix') for version in ('v1', 'v2')})
            if path not in names:
                self.send_error(404)
                return
            name, mime = names[path]
            file = self.server.packages / name
            source, size = file.open('rb'), file.stat().st_size
        with source:
            first, last, status = 0, size - 1, 200
            if self.headers.get('Range'):
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers['Range'])
                if not match:
                    self.send_error(416)
                    return
                first = int(match[1])
                last = min(int(match[2]) if match[2] else last, size - 1)
                if not 0 <= first <= last < size:
                    self.send_error(416)
                    return
                status = 206
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(last - first + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            if status == 206:
                self.send_header('Content-Range', 'bytes ' + str(first) + '-' + str(last) + '/' + str(size))
            self.end_headers()
            if not head:
                source.seek(first)
                remaining = last - first + 1
                while remaining:
                    data = source.read(min(65536, remaining))
                    if not data:
                        raise ValueError('Truncated BB fixture')
                    self.wfile.write(data)
                    remaining -= len(data)

    def do_GET(self):
        self.serve()

    def do_HEAD(self):
        self.serve(head=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    with FixtureServer(('127.0.0.1', args.port), args.packages) as server:
        server.serve_forever()
