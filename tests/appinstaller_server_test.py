"""Native transport serves unchanged BB bytes and correct range responses."""

from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools.ci.windows_appinstaller_server import FixtureServer


class AppInstallerServerTest(unittest.TestCase):
    def test_release_switch_ranges_and_path_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for version in ('v1', 'v2'):
                (root / ('msix_appinstaller_' + version + '.appinstaller')).write_bytes(version.encode())
                (root / ('appinstaller_signed_desktop_' + version + '.msix')).write_bytes(bytes(range(256)) * 1024)
            with FixtureServer(('127.0.0.1', 0), root) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = 'http://127.0.0.1:' + str(server.server_port)
                    with urlopen(base + '/ready', timeout=5) as response:
                        self.assertEqual(response.read(), b'MSIX_APPINSTALLER_READY')
                    with urlopen(base + '/desktop.appinstaller', timeout=5) as response:
                        self.assertEqual(response.read(), b'v1')
                        self.assertEqual(response.headers['Content-Type'], 'application/appinstaller')
                    with urlopen(Request(base + '/use-v2', data=b''), timeout=5) as response:
                        self.assertEqual(response.status, 204)
                    with urlopen(base + '/desktop.appinstaller', timeout=5) as response:
                        self.assertEqual(response.read(), b'v2')
                    url = base + '/appinstaller_signed_desktop_v2.msix'
                    with urlopen(Request(url, headers={'Range': 'bytes=65530-65550'}), timeout=5) as response:
                        self.assertEqual(response.status, 206)
                        self.assertEqual(response.headers['Content-Range'], 'bytes 65530-65550/262144')
                        self.assertEqual(response.read(), (bytes(range(256)) * 1024)[65530:65551])
                    with urlopen(Request(url, method='HEAD'), timeout=5) as response:
                        self.assertEqual(response.headers['Content-Length'], '262144')
                        self.assertEqual(response.read(), b'')
                    for address in ('/../AppxManifest.xml', '/%2e%2e/msix_appinstaller_v1.appinstaller'):
                        with self.assertRaises(HTTPError) as error:
                            urlopen(base + address, timeout=5)
                        self.assertEqual(error.exception.code, 404)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
