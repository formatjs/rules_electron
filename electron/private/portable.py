"""Portable Windows launchers from immutable app bytes and declared NSIS tools."""

import json
from pathlib import Path
import re
import sys

from electron.private.identity import build_identity
from electron.private.icons import validate_ico
from electron.private.nsis import compile_executable, literal, payload_inventory
from electron.private.update import _filename, _version


PARAMETERS = r'''Function PortableParameters
System::Call 'kernel32::GetCommandLineW() p.r0'
System::Call 'kernel32::lstrlenW(p r0) i.r1'
IntCmp $1 ${NSIS_MAX_STRLEN} args_failed args_load args_failed
args_load:
System::Call 'kernel32::GetCommandLineW() w.r0'
StrCpy $1 0
StrCpy $2 0
args_loop:
StrCpy $3 $0 1 $1
StrCmp $3 "" args_done
StrCmp $3 '$\"' args_quote
StrCmp $2 0 0 args_next
StrCmp $3 " " args_done
StrCmp $3 '$\t' args_done
Goto args_next
args_quote:
IntOp $2 $2 ^ 1
args_next:
IntOp $1 $1 + 1
Goto args_loop
args_done:
StrCpy $PortableArgs $0 "" $1
ClearErrors
Return
args_failed:
SetErrors
FunctionEnd'''


def portable_script(app, package_json, app_id, product_name, executable_name, output,
                    architecture='x64', compression='7z', payload_archive='', directory_manifest='',
                    installer_icon='', app_filename='', build_version='', build_number='', path_format=None):
    def source_path(value, role='app'):
        path = Path(value)
        return path_format(path, role) if path_format else str(path.resolve())

    if architecture not in ('x64', 'arm64'):
        raise ValueError('Unsupported Windows payload architecture')
    if compression not in ('7z', 'zlib', 'bzip2', 'lzma', 'off'):
        raise ValueError('Unsupported NSIS compressor')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', app_id):
        raise ValueError('Portable app_id must be an ASCII application identifier')
    _filename(app_id)
    _filename(product_name)
    executable = executable_name if executable_name.endswith('.exe') else executable_name + '.exe'
    _filename(executable)
    app_filename = app_filename or executable[:-4]
    _filename(app_filename)
    if installer_icon:
        validate_ico(installer_icon)
    if compression == '7z' and not payload_archive:
        raise ValueError('Portable 7z compression requires a declared payload archive')
    files, directories, _ = payload_inventory(app, executable, directory_manifest)
    version = _version(json.loads(Path(package_json).read_text(encoding='utf-8'))['version'])
    file_version = build_identity(version, build_version, build_number, 'windows')
    numeric = file_version.split('-', 1)[0].split('+', 1)[0].split('.')
    numeric += ['0'] * (4 - len(numeric))
    command_executable = executable.replace('$', '$$').replace("'", "$\\'")
    q = literal
    lines = [
        '# -*- coding: utf-8 -*-', 'Unicode true', 'RequestExecutionLevel user',
        'SilentInstall silent', 'AutoCloseWindow true', 'SetDateSave off',
        *(['SetCompress off'] if compression in ('7z', 'off') else ['SetCompressor /SOLID ' + compression]),
        *(['SetCompressorDictSize 8'] if compression == 'lzma' else []),
        '!include "LogicLib.nsh"', '!include "x64.nsh"', 'Var PortableArgs',
        'Name ' + q(product_name), 'OutFile ' + q(source_path(output, 'output')),
        *(['Icon ' + q(source_path(installer_icon, 'installer_icon'))] if installer_icon else []),
        'VIProductVersion ' + '.'.join(numeric),
        'VIAddVersionKey "ProductName" ' + q(product_name),
        'VIAddVersionKey "FileDescription" ' + q(product_name + ' Portable'),
        'VIAddVersionKey "FileVersion" ' + q(file_version),
        'VIAddVersionKey "ProductVersion" ' + q(version),
        *PARAMETERS.splitlines(), 'Function .onInit',
        '${Unless} ${' + ('IsNativeARM64' if architecture == 'arm64' else 'IsNativeAMD64') + '}',
        'SetErrorLevel 1', 'Abort "Portable app requires matching native Windows architecture."',
        '${EndUnless}', 'FunctionEnd', 'Section "Launch"',
        'Call PortableParameters', 'IfErrors portable_start_failed',
        'InitPluginsDir', 'StrCpy $INSTDIR "$PLUGINSDIR\\app"',
        'ClearErrors', 'CreateDirectory "$INSTDIR"', 'IfErrors portable_failed',
    ]
    if compression == '7z':
        lines += ['SetOutPath "$PLUGINSDIR"',
                  'File "/oname=payload.7z" ' + q(source_path(payload_archive, 'payload_archive')),
                  'IfErrors portable_failed', 'SetOutPath "$INSTDIR"',
                  'Nsis7z::Extract "$PLUGINSDIR\\payload.7z"']
    for name in sorted(directories):
        lines += ['CreateDirectory "$INSTDIR\\' + name.replace('/', '\\').replace('$', '$$') + '"',
                  'IfErrors portable_failed']
    for name, path in files:
        if compression == '7z':
            target = '"$INSTDIR\\' + name.replace('/', '\\').replace('$', '$$') + '"'
            lines += ['ClearErrors', 'FileOpen $0 ' + target + ' r', 'IfErrors portable_failed',
                      'FileSeek $0 0 END $1', 'FileClose $0',
                      'IntCmp $1 ' + str(path.stat().st_size) + ' +2', 'Goto portable_failed']
        else:
            parent = str(Path(name).parent).replace('/', '\\').replace('$', '$$')
            lines += ['SetOutPath "$INSTDIR' + ('\\' + parent if parent != '.' else '') + '"',
                      'File ' + q('/oname=' + Path(name).name) + ' ' + q(source_path(path)),
                      'IfErrors portable_failed']
    lines += ['StrCpy $4 ' + q(app_filename)]
    for variable, value in [('PORTABLE_EXECUTABLE_DIR', '"$EXEDIR"'),
                            ('PORTABLE_EXECUTABLE_FILE', '"$EXEPATH"'),
                            ('PORTABLE_EXECUTABLE_APP_FILENAME', 'r4')]:
        lines += ["System::Call 'kernel32::SetEnvironmentVariableW(w \"" + variable + '\", w ' + value + ") i.r0'",
                  'StrCmp $0 0 portable_failed']
    lines += [
        'SetOutPath "$EXEDIR"', 'ClearErrors',
        'ExecWait \'"$INSTDIR\\' + command_executable + '" $PortableArgs\' $R2',
        'IfErrors portable_failed', 'Goto portable_cleanup',
        'portable_failed:', 'StrCpy $R2 1', 'portable_cleanup:',
        'SetOutPath "$EXEDIR"', 'StrCpy $R3 150', 'portable_cleanup_retry:',
        'ClearErrors', 'RMDir /r "$INSTDIR"', 'IfErrors 0 portable_cleanup_done',
        'IntOp $R3 $R3 - 1', 'IntCmp $R3 0 portable_cleanup_failed portable_cleanup_failed portable_cleanup_wait',
        'portable_cleanup_wait:', 'Sleep 200', 'Goto portable_cleanup_retry',
        'portable_cleanup_failed:', 'StrCmp $R2 0 0 portable_cleanup_done', 'StrCpy $R2 1',
        'portable_cleanup_done:', 'SetErrorLevel $R2', 'Goto portable_done',
        'portable_start_failed:', 'SetErrorLevel 1', 'portable_done:', 'SectionEnd',
    ]
    return '\n'.join(lines) + '\n'


def build_portable(manifest, output, script):
    return compile_executable(manifest, output, script, portable_script)


if __name__ == '__main__':
    build_portable(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2], sys.argv[3])
