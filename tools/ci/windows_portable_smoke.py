"""Execute BB-built portable payloads; verify forwarding and owned cleanup."""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import winreg

from windows_nsis_smoke import known_folder


APP_ID = 'org.example.sample-desktop'
VARIABLES = ('PORTABLE_EXECUTABLE_DIR', 'PORTABLE_EXECUTABLE_FILE', 'PORTABLE_EXECUTABLE_APP_FILENAME')
ARGUMENTS = ['words with spaces', 'embedded"quote', 'trailing\\', '世界 😀', '', '/D=Z:\\must-not-install']


def registrations():
    keys = ['Software\\' + APP_ID, 'Software\\Classes\\sample-desktop',
            'Software\\Classes\\.rules-electron-sample', 'Software\\Classes\\.rules-electron-cleanup',
            'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + APP_ID]
    result = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            for key in keys:
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view):
                        result.append(True)
                except FileNotFoundError:
                    result.append(False)
    result += [(known_folder(folder) / 'Sample Desktop.lnk').exists() for folder in (2, 16)]
    return result


def terminate(process):
    if process.poll() is None:
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, timeout=30)
        process.wait(timeout=30)


def check_report(report_file, executable, architecture, arguments, original):
    if not report_file.is_file() or report_file.stat().st_size > 1024**2:
        raise RuntimeError('PORTABLE_REPORT_MISSING_OR_OVERSIZED')
    report = json.loads(report_file.read_text(encoding='utf-8'))
    if (report['architecture'] != architecture or report['platform'] != 'win32'
            or report['app_version'] != '1.0.0' or report['update_version'] != '2.0.0'
            or report['windows_store']):
        raise RuntimeError('PORTABLE_RUNTIME_REPORT_FAILED')
    portable = report['portable']
    if (Path(portable['directory']).resolve() != executable.parent.resolve()
            or Path(portable['file']).resolve() != executable.resolve()
            or portable['app_filename'] != 'Sample Desktop'):
        raise RuntimeError('PORTABLE_ENVIRONMENT_FAILED')
    marker = portable['arguments'].index('--portable-arguments')
    if portable['arguments'][marker + 1:] != arguments:
        raise RuntimeError('PORTABLE_ARGUMENT_FORWARDING_FAILED')
    unpacked = Path(portable['executable']).parent
    if (unpacked.name != 'app' or not unpacked.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
            or unpacked.parent.exists() or unpacked.exists()):
        raise RuntimeError('PORTABLE_OWNED_CLEANUP_FAILED')
    if executable.read_bytes() != original:
        raise RuntimeError('PORTABLE_SOURCE_CHANGED')
    return str(unpacked).casefold()


if __name__ == '__main__':
    architecture = sys.argv[2]
    native = {'amd64': 'x64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if platform.system() != 'Windows' or native != architecture:
        raise RuntimeError('Portable smoke requires matching native Windows host')
    before = registrations()
    parent_environment = {name: os.environ.get(name) for name in VARIABLES}
    with tempfile.TemporaryDirectory(prefix='portable source 世界 ') as temporary:
        root = Path(temporary)
        executable = root / 'Renamed portable 世界.exe'
        shutil.copyfile(Path(sys.argv[1]) / 'portable.exe', executable)
        original = executable.read_bytes()
        outside = root / 'outside extraction'
        outside.mkdir()
        sentinel = outside / 'must survive.txt'
        sentinel.write_bytes(b'outside extraction ownership')
        runs = []

        def launch(index, exit_code):
            report = root / ('report-' + str(index) + '.json')
            data = root / ('data-' + str(index))
            environment = dict(os.environ, APPDATA=str(data / 'appdata'), LOCALAPPDATA=str(data / 'localappdata'),
                               RULES_ELECTRON_PORTABLE_REPORT=str(report), RULES_ELECTRON_PORTABLE_EXIT=str(exit_code),
                               RULES_ELECTRON_PORTABLE_JUNCTION=str(outside))
            environment.pop('ELECTRON_RUN_AS_NODE', None)
            environment.pop('NODE_OPTIONS', None)
            process = subprocess.Popen([str(executable), '--smoke', '--disable-gpu', '--disable-dev-shm-usage',
                                        '--user-data-dir=' + str(data / 'profile'), '--', '--portable-arguments', *ARGUMENTS],
                                       cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            runs.append(process)
            return process, report

        try:
            for index, exit_code in enumerate((0, 42)):
                process, report = launch(index, exit_code)
                actual = process.wait(timeout=240)
                print('PORTABLE_LAUNCH_EXIT ' + str(actual), flush=True)
                if actual != exit_code:
                    raise RuntimeError('PORTABLE_EXIT_FORWARDING_FAILED')
                check_report(report, executable, architecture, ARGUMENTS, original)
                if sentinel.read_bytes() != b'outside extraction ownership':
                    raise RuntimeError('PORTABLE_JUNCTION_TARGET_CHANGED')
            concurrent = [launch(index, 0) for index in (2, 3)]
            paths = []
            for process, report in concurrent:
                if process.wait(timeout=240) != 0:
                    raise RuntimeError('PORTABLE_CONCURRENT_LAUNCH_FAILED')
                paths.append(check_report(report, executable, architecture, ARGUMENTS, original))
            if len(set(paths)) != 2:
                raise RuntimeError('PORTABLE_EXTRACTION_COLLISION')
            if sentinel.read_bytes() != b'outside extraction ownership':
                raise RuntimeError('PORTABLE_JUNCTION_TARGET_CHANGED')
        finally:
            for process in runs:
                terminate(process)
    if registrations() != before or {name: os.environ.get(name) for name in VARIABLES} != parent_environment:
        raise RuntimeError('PORTABLE_PARENT_STATE_CHANGED')
    print('PORTABLE_NATIVE_SMOKE_OK', flush=True)
