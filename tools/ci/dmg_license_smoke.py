"""Exercise hdiutil's interactive agreement on a matching native host."""

from collections import namedtuple
import base64
import errno
import fcntl
import os
import json
import plistlib
import platform
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from zipfile import ZipFile


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
    set maxProcesses to 0
    set maxWindows to 0
    set sawBody to false
    set sawAgree to false
    set sawDisagree to false
    tell application "System Events"
        repeat 40 times
            set targets to application processes
            if (count targets) > maxProcesses then set maxProcesses to count targets
            repeat with targetProcess in targets
                set processWindows to {}
                try
                    set processWindows to windows of targetProcess
                end try
                if (count processWindows) > maxWindows then set maxWindows to count processWindows
                repeat with targetWindow in processWindows
                    set bodyMatches to false
                    set agreeControl to missing value
                    set disagreeControl to missing value
                    repeat with element in entire contents of targetWindow
                        try
                            if (value of element as text) contains "Sample Desktop example license, version 1." then set bodyMatches to true
                        end try
                        try
                            if (role of element as text) is "AXButton" then
                                if (name of element as text) is "Agree" then set agreeControl to element
                                if (name of element as text) is "Disagree" then set disagreeControl to element
                            end if
                        end try
                    end repeat
                    if bodyMatches then set sawBody to true
                    if agreeControl is not missing value then set sawAgree to true
                    if disagreeControl is not missing value then set sawDisagree to true
                    if bodyMatches and agreeControl is not missing value and disagreeControl is not missing value then
                        click disagreeControl
                        return "declined," & maxProcesses & "," & maxWindows & "," & sawBody & "," & sawAgree & "," & sawDisagree
                    end if
                end repeat
            end repeat
            delay 0.5
        end repeat
    end tell
    return "not-found," & maxProcesses & "," & maxWindows & "," & sawBody & "," & sawAgree & "," & sawDisagree
end run
'''

    def attached():
        information = subprocess.run(['/usr/bin/hdiutil', 'info', '-plist'],
                                     capture_output=True, check=True, timeout=30)
        return [entry for entry in plistlib.loads(information.stdout).get('images', [])
                if entry.get('image-path') and Path(entry['image-path']).resolve() == image.resolve()]

    if attached():
        raise RuntimeError('DMG_LICENSE_DIALOG_IMAGE_ALREADY_ATTACHED')
    try:
        opened = subprocess.run(['/usr/bin/osascript', '-e', '''
on run argv
    tell application "Finder"
        activate
        open (POSIX file (item 1 of argv))
    end tell
end run
''', str(image)],
                                capture_output=True, timeout=30)
        result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, timeout=30)
        time.sleep(1)
        summary = {
            'opened': opened.returncode == 0, 'observer_exit_code': result.returncode,
            'declined': False,
            'attached_images': len(attached()),
        }
        fields = result.stdout.strip().split(b',')
        if (result.returncode == 0 and len(fields) == 6 and fields[0] in (b'declined', b'not-found')
                and all(value.isdigit() and len(value) <= 3 for value in fields[1:3])
                and all(value in (b'true', b'false') for value in fields[3:])):
            summary.update(declined=fields[0] == b'declined', processes=int(fields[1]), windows=int(fields[2]),
                           body=fields[3] == b'true', agree=fields[4] == b'true', disagree=fields[5] == b'true')
        print('DMG_LICENSE_DIALOG ' + json.dumps(summary, sort_keys=True), flush=True)
        return summary
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
                print('DMG_LICENSE_TIMEOUT_STATE ' + json.dumps({
                    'output_bytes': len(output), 'header': b'Sample Desktop example license, version 1.' in output,
                    'answered': answered, 'pager_quit': pager_quit,
                    'answer_prompt': bool(re.search(br'\b[yY]/[nN]\b', output)),
                }, sort_keys=True), flush=True)
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
                    if not answered and re.search(br'\b[yY]/[nN]\b', output):
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


if __name__ == '__main__':
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('DMG license probe requires native macOS ARM64')
    with ZipFile(sys.argv[1]) as archive, tempfile.TemporaryDirectory() as temporary:
        members = [entry for entry in archive.infolist() if entry.filename == 'macos_aarch64/packages/release_dmg.dmg']
        if len(members) != 1 or not 0 < members[0].file_size <= 1024**3:
            raise RuntimeError('DMG_LICENSE_PROBE_INVALID_ARCHIVE')
        image = Path(temporary) / 'release.dmg'
        with archive.open(members[0]) as source, image.open('wb') as target:
            remaining = members[0].file_size
            while remaining:
                data = source.read(min(remaining, 1024**2))
                if not data:
                    raise RuntimeError('DMG_LICENSE_PROBE_TRUNCATED_IMAGE')
                target.write(data)
                remaining -= len(data)
        subprocess.run(['/usr/bin/hdiutil', 'verify', str(image)], check=True, capture_output=True, timeout=120)
        inspect_license(image)
        result = inspect_dialog(image)
        if not result['declined'] or result['attached_images']:
            raise RuntimeError('DMG_LICENSE_DIALOG_DECLINE_FAILED')
        print('DMG_LICENSE_DIALOG_DECLINED_OK', flush=True)
