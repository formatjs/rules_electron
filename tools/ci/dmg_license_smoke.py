"""Exercise hdiutil's interactive agreement on a matching native host."""

from collections import namedtuple
import base64
import errno
import fcntl
import os
import json
import plistlib
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time


Attachment = namedtuple('Attachment', 'returncode output answered')


def inspect_license(image):
    with image.open('rb') as source:
        source.seek(-512, 2)
        footer = source.read(512)
        offset, size = struct.unpack_from('>QQ', footer, 216)
        if footer[:4] != b'koly' or not 0 < size <= 64 * 1024**2:
            raise RuntimeError('DMG_LICENSE_INVALID_RESOURCES')
        source.seek(offset)
        resources = plistlib.loads(source.read(size))['resource-fork']
    bodies = [entry['Data'] for entry in resources.get('RTF ', []) if entry['ID'] == '5000']
    if len(bodies) != 1 or len(bodies[0]) > 2 * 1024**2:
        raise RuntimeError('DMG_LICENSE_INVALID_BODY')
    script = '''
ObjC.import('AppKit');
function run(argv) {
    const data = $.NSData.alloc.initWithBase64EncodedStringOptions($(argv[0]), 0);
    const body = $.NSAttributedString.alloc.initWithRTFDocumentAttributes(data, null);
    const text = body ? ObjC.unwrap(body.string) : '';
    return JSON.stringify({decoded: Boolean(body), header: text.includes('Sample Desktop example license, version 1.'), length: text.length});
}
'''
    result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', script,
                             base64.b64encode(bodies[0]).decode('ascii')],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('DMG_LICENSE_NATIVE_DECODE_FAILED')
    summary = json.loads(result.stdout)
    if (set(summary) != {'decoded', 'header', 'length'} or type(summary['decoded']) is not bool
            or type(summary['header']) is not bool or type(summary['length']) is not int):
        raise RuntimeError('DMG_LICENSE_INVALID_NATIVE_SUMMARY')
    print('DMG_LICENSE_NATIVE_BODY ' + json.dumps(summary, sort_keys=True), flush=True)
    if not summary['decoded'] or not summary['header']:
        raise RuntimeError('DMG_LICENSE_NATIVE_BODY_FAILED')


def interactive_attach(arguments, answer, timeout=120):
    if answer not in (b'n', b'y'):
        raise ValueError('Expected one explicit license answer')
    pid, terminal = pty.fork()
    if pid == 0:
        try:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 100, 0, 0))
            os.execve(arguments[0], arguments, dict(os.environ, TERM='xterm-256color'))
        except BaseException:
            os._exit(127)
    deadline = time.monotonic() + timeout
    output = bytearray()
    answered, pager_quit, alive, closed = False, False, True, False
    try:
        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError('DMG_LICENSE_INTERACTIVE_TIMEOUT')
            if not closed and select.select([terminal], [], [], 0.1)[0]:
                try:
                    block = os.read(terminal, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    block = b''
                if block:
                    output.extend(block)
                    if len(output) > 2 * 1024**2:
                        raise RuntimeError('DMG_LICENSE_RESPONSE_TOO_LARGE')
                    if not answered and re.search(br'\[[yY]/[nN]\]', output):
                        os.write(terminal, answer + b'\n')
                        answered = True
                    elif not pager_quit and (b'(END)' in output or b'--More--' in output):
                        os.write(terminal, b'q')
                        pager_quit = True
                else:
                    closed = True
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited:
                alive = False
                return Attachment(os.waitstatus_to_exitcode(status), bytes(output), answered)
            if closed:
                time.sleep(0.05)
    finally:
        if alive:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
        os.close(terminal)
