"""Exercise hdiutil's interactive agreement on a matching native host."""

from collections import namedtuple
import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time


Attachment = namedtuple('Attachment', 'returncode output answered')


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
