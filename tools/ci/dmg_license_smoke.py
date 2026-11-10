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


def inspect_license(image, require_unicode=False):
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
    return JSON.stringify({decoded: Boolean(body), header: text.includes('Sample Desktop example license, version 1.'),
        unicode: text.includes('Example Unicode text: 世界 😀.'), length: text.length});
}
'''
    result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', script,
                             base64.b64encode(bodies[0][1]).decode('ascii'), bodies[0][0]],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('DMG_LICENSE_NATIVE_DECODE_FAILED')
    summary = json.loads(result.stdout)
    if (set(summary) != {'decoded', 'header', 'unicode', 'length'} or type(summary['decoded']) is not bool
            or type(summary['unicode']) is not bool
            or type(summary['header']) is not bool or type(summary['length']) is not int):
        raise RuntimeError('DMG_LICENSE_INVALID_NATIVE_SUMMARY')
    print('DMG_LICENSE_NATIVE_BODY ' + json.dumps(summary, sort_keys=True), flush=True)
    if not summary['decoded'] or not summary['header'] or (require_unicode and not summary['unicode']):
        raise RuntimeError('DMG_LICENSE_NATIVE_BODY_FAILED')


def inspect_dialog(image):
    script = '''
on run argv
    set maxProcesses to 0
    set maxWindows to 0
    set sawBody to false
    set sawAgree to false
    set sawDisagree to false
    set maxButtons to 0
    set maxTexts to 0
    set maxElements to 0
    set sawImageError to false
    set sawOK to false
    set diskError to "none"
    tell application "System Events"
        repeat 20 times
            set targets to {}
            repeat with processId in argv
                set targets to targets & (application processes whose unix id is (processId as integer))
            end repeat
            if (count argv) is 0 then
                set targets to application processes whose background only is false or name is "DiskImageMounter" or name is "diskimages-helper" or name is "CoreServicesUIAgent"
            end if
            if (count targets) > maxProcesses then set maxProcesses to count targets
            repeat with targetProcess in targets
                set processWindows to {}
                try
                    set processWindows to windows of targetProcess
                end try
                if (count processWindows) > maxWindows then set maxWindows to count processWindows
                repeat with targetWindow in processWindows
                    set bodyMatches to false
                    set buttonCount to 0
                    set textCount to 0
                    set agreeControl to missing value
                    set disagreeControl to missing value
                    set elements to {}
                    try
                        with timeout of 2 seconds
                            set elements to (get entire contents of targetWindow)
                        end timeout
                    end try
                    if (count elements) > maxElements then set maxElements to count elements
                    repeat with elementReference in elements
                        set currentElement to contents of elementReference
                        try
                            if (value of currentElement as text) contains "Sample Desktop example license, version 1." then set bodyMatches to true
                        end try
                        try
                            if (name of currentElement as text) contains "Sample Desktop example license, version 1." then set bodyMatches to true
                        end try
                        try
                            if (description of currentElement as text) contains "Sample Desktop example license, version 1." then set bodyMatches to true
                        end try
                        try
                            if (role of currentElement as text) is "AXButton" then
                                set buttonCount to buttonCount + 1
                                if (name of currentElement as text) is "Agree" then set agreeControl to currentElement
                                if (name of currentElement as text) is "Disagree" then set disagreeControl to currentElement
                                if (name of currentElement as text) is "OK" then set sawOK to true
                            end if
                            if (role of currentElement as text) is in {"AXStaticText", "AXTextArea"} then set textCount to textCount + 1
                        end try
                        set elementText to ""
                        try
                            set elementText to value of currentElement as text
                        end try
                        try
                            set elementText to elementText & " " & (name of currentElement as text)
                        end try
                        if elementText contains "couldn't be opened" or elementText contains "couldn’t be opened" or elementText contains "could not be opened" or elementText contains "can't be opened" then set sawImageError to true
                        if elementText contains "no mountable file systems" then set diskError to "filesystem"
                        if elementText contains "not recognized" then set diskError to "format"
                        if elementText contains "permission" or elementText contains "not permitted" then set diskError to "permission"
                        if elementText contains "no such file" or elementText contains "not found" then set diskError to "missing"
                        if elementText contains "resource busy" then set diskError to "busy"
                        if elementText contains "corrupt" or elementText contains "damaged" then set diskError to "corrupt"
                    end repeat
                    if buttonCount > maxButtons then set maxButtons to buttonCount
                    if textCount > maxTexts then set maxTexts to textCount
                    if bodyMatches then set sawBody to true
                    if agreeControl is not missing value then set sawAgree to true
                    if disagreeControl is not missing value then set sawDisagree to true
                    if bodyMatches and agreeControl is not missing value and disagreeControl is not missing value then
                        click disagreeControl
                        return "declined," & maxProcesses & "," & maxWindows & "," & sawBody & "," & sawAgree & "," & sawDisagree & "," & maxButtons & "," & maxTexts & "," & maxElements & "," & sawImageError & "," & sawOK & "," & diskError
                    end if
                end repeat
            end repeat
            delay 0.5
        end repeat
    end tell
    return "not-found," & maxProcesses & "," & maxWindows & "," & sawBody & "," & sawAgree & "," & sawDisagree & "," & maxButtons & "," & maxTexts & "," & maxElements & "," & sawImageError & "," & sawOK & "," & diskError
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
        access = subprocess.run(['/usr/bin/osascript', '-e', 'tell application "System Events" to get UI elements enabled'],
                                capture_output=True, timeout=15)
        enabled = {b'true': True, b'false': False}.get(access.stdout.strip())
        print('DMG_LICENSE_ACCESSIBILITY ' + json.dumps({'enabled': enabled, 'observer_exit_code': access.returncode}), flush=True)
        opened = subprocess.run(['/usr/bin/osascript', '-e', '''
on run argv
    set targetImage to (POSIX file (item 1 of argv)) as alias
    tell application "Finder"
        activate
        open targetImage
    end tell
end run
''', str(image)],
                                capture_output=True, timeout=30)
        owners = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', '''
ObjC.import('CoreGraphics');
ObjC.import('Foundation');
function run() {
    let visible = 0;
    let stage = 0;
    try {
    for (let attempt = 0; attempt < 24; attempt++) {
        stage = 1;
        const raw = $.CGWindowListCopyWindowInfo(1, 0);
        stage = 2;
        const windows = ObjC.deepUnwrap(ObjC.castRefToObject(raw)) || [];
        stage = 3;
        visible = windows.length;
        stage = 4;
        const owners = [...new Set(windows.filter(window =>
            /license|agreement|release\\.dmg|Sample Desktop/i.test(window.kCGWindowName || '')
        ).map(window => window.kCGWindowOwnerPID))];
        if (owners.length) return JSON.stringify({owners, visible});
        stage = 5;
        $.NSThread.sleepForTimeInterval(0.5);
    }
    return JSON.stringify({owners: [], visible});
    } catch (error) {
        return JSON.stringify({owners: [], visible: Number(visible) || 0, error_stage: stage});
    }
}
'''], capture_output=True, timeout=20)
        candidates = json.loads(owners.stdout) if owners.returncode == 0 else {'owners': [], 'visible': 0}
        identifiers = candidates.get('owners', [])
        if (not isinstance(identifiers, list) or len(identifiers) > 16
                or any(type(value) is not int or not 0 < value <= 2**31 for value in identifiers)
                or type(candidates.get('visible')) is not int or not 0 <= candidates['visible'] <= 4096):
            raise RuntimeError('DMG_LICENSE_INVALID_WINDOW_SUMMARY')
        print('DMG_LICENSE_WINDOW_OWNERS ' + json.dumps({'candidates': len(identifiers),
              'visible_windows': candidates['visible'], 'observer_exit_code': owners.returncode,
              'error_stage': candidates.get('error_stage') if candidates.get('error_stage') in range(1, 6) else None,
              'type_error': b'TypeError' in owners.stderr, 'reference_error': b'ReferenceError' in owners.stderr,
              'core_graphics_symbol': b'CGWindowListCopyWindowInfo' in owners.stderr}, sort_keys=True), flush=True)
        result = subprocess.run(['/usr/bin/osascript', '-e', script, *map(str, identifiers)],
                                capture_output=True, timeout=120)
        time.sleep(1)
        summary = {
            'opened': opened.returncode == 0, 'observer_exit_code': result.returncode,
            'declined': False,
            'attached_images': len(attached()),
        }
        open_error = re.search(br'\((-?\d{1,10})\)\s*$', opened.stderr)
        summary['open_error_code'] = int(open_error[1]) if open_error else None
        observer_error = re.search(br'\((-?\d{1,10})\)\s*$', result.stderr)
        summary['observer_error_code'] = int(observer_error[1]) if observer_error else None
        fields = result.stdout.strip().split(b',')
        if (result.returncode == 0 and len(fields) == 12 and fields[0] in (b'declined', b'not-found')
                and all(value.isdigit() and len(value) <= 3 for value in fields[1:3] + fields[6:9])
                and all(value in (b'true', b'false') for value in fields[3:6] + fields[9:11])
                and fields[11] in (b'none', b'filesystem', b'format', b'permission', b'missing', b'busy', b'corrupt')):
            summary.update(declined=fields[0] == b'declined', processes=int(fields[1]), windows=int(fields[2]),
                           body=fields[3] == b'true', agree=fields[4] == b'true', disagree=fields[5] == b'true',
                           buttons=int(fields[6]), text_controls=int(fields[7]), elements=int(fields[8]),
                           image_error=fields[9] == b'true', ok=fields[10] == b'true',
                           disk_error=fields[11].decode('ascii'))
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
    fixture = sys.argv[2] if len(sys.argv) > 2 else 'release_dmg.dmg'
    if fixture not in ('release_dmg.dmg', 'release_dmg_rtf.dmg', 'release_dmg_japanese.dmg'):
        raise RuntimeError('DMG_LICENSE_PROBE_INVALID_FIXTURE')
    with ZipFile(sys.argv[1]) as archive, tempfile.TemporaryDirectory() as temporary:
        members = [entry for entry in archive.infolist() if entry.filename == 'macos_aarch64/packages/' + fixture]
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
        inspect_license(image, require_unicode=fixture != 'release_dmg.dmg')
        result = inspect_dialog(image)
        if not result['declined'] or result['attached_images']:
            raise RuntimeError('DMG_LICENSE_DIALOG_DECLINE_FAILED')
        print('DMG_LICENSE_DIALOG_DECLINED_OK', flush=True)
