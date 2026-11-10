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
    bodies = [(kind, entry['Data']) for kind in ('RTF ', 'TEXT')
              for entry in resources.get(kind, []) if entry['ID'] == '5000']
    if len(bodies) != 1 or len(bodies[0][1]) > 2 * 1024**2:
        raise RuntimeError('DMG_LICENSE_INVALID_BODY')
    script = '''
ObjC.import('AppKit');
function run(argv) {
    const data = $.NSData.alloc.initWithBase64EncodedStringOptions($(argv[0]), 0);
    const plain = argv[1] === 'TEXT';
    const body = plain ? $.NSString.alloc.initWithDataEncoding(data, $.NSMacOSRomanStringEncoding)
        : $.NSAttributedString.alloc.initWithRTFDocumentAttributes(data, null);
    const text = body ? ObjC.unwrap(plain ? body : body.string) : '';
    return JSON.stringify({decoded: Boolean(body), header: text.includes('Sample Desktop example license, version 1.'), length: text.length});
}
'''
    result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', script,
                             base64.b64encode(bodies[0][1]).decode('ascii'), bodies[0][0]],
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


def inspect_dialog(image):
    script = '''
on run
    tell application "System Events"
        repeat 40 times
            set targets to application processes whose bundle identifier is "com.apple.DiskImageMounter"
            repeat with targetProcess in targets
                repeat with targetWindow in windows of targetProcess
                    set bodyMatches to false
                    repeat with element in entire contents of targetWindow
                        try
                            if (value of element as text) contains "Sample Desktop example license, version 1." then set bodyMatches to true
                        end try
                    end repeat
                    if bodyMatches and (exists button "Disagree" of targetWindow) and (exists button "Agree" of targetWindow) then
                        click button "Disagree" of targetWindow
                        return "declined"
                    end if
                end repeat
            end repeat
            delay 0.5
        end repeat
    end tell
    return "not-found"
end run
'''

    def attached():
        information = subprocess.run(['/usr/bin/hdiutil', 'info', '-plist'],
                                     capture_output=True, check=True, timeout=30)
        return [entry for entry in plistlib.loads(information.stdout).get('images', [])
                if entry.get('image-path') == str(image)]

    if attached():
        raise RuntimeError('DMG_LICENSE_DIALOG_IMAGE_ALREADY_ATTACHED')
    try:
        opened = subprocess.run(['/usr/bin/open', '-a', 'DiskImageMounter', str(image)],
                                capture_output=True, timeout=30)
        result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, timeout=30)
        time.sleep(1)
        print('DMG_LICENSE_DIALOG ' + json.dumps({
            'opened': opened.returncode == 0, 'observer_exit_code': result.returncode,
            'declined': result.returncode == 0 and result.stdout.strip() == b'declined',
            'attached_images': len(attached()),
        }, sort_keys=True), flush=True)
    finally:
        for entry in attached():
            devices = [value['dev-entry'] for value in entry.get('system-entities', []) if value.get('dev-entry')]
            if not devices:
                raise RuntimeError('DMG_LICENSE_DIALOG_CLEANUP_FAILED')
            subprocess.run(['/usr/bin/hdiutil', 'detach', devices[0]], capture_output=True, check=True, timeout=120)


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
