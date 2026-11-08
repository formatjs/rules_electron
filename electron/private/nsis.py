"""Deterministic NSIS input generation; installer removes only owned files."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import sys
import tempfile

from electron.private.update import _filename, _version
from electron.private.identity import build_identity
from electron.private.icons import validate_ico


def literal(value):
    if any(ord(c) < 32 for c in value) or "${" in value or "$%" in value:
        raise ValueError("NSIS literals cannot contain controls or preprocessor expressions")
    return '"' + value.replace("$", "$$").replace('"', '$\\"') + '"'


def installer_script(app, package_json, app_id, product_name, executable_name,
                     output, protocols=(), desktop_shortcut=False, compression="zlib",
                     updater_cache_name="", architecture="x64", payload_archive="",
                     build_version="", build_number="", file_associations=None, app_user_model_id="",
                     installer_icon="", uninstaller_icon=""):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", app_id):
        raise ValueError("NSIS app_id must be an ASCII application identifier")
    _filename(app_id)
    app_user_model_id = app_user_model_id or app_id
    if len(app_user_model_id.encode('utf-16-le')) > 256 or any(c.isspace() for c in app_user_model_id):
        raise ValueError("AppUserModelID must contain at most 128 UTF-16 units and no whitespace")
    literal(app_user_model_id)
    for icon in [installer_icon, uninstaller_icon]:
        if icon:
            validate_ico(icon)
    _filename(product_name)
    executable = executable_name if executable_name.endswith(".exe") else executable_name + ".exe"
    _filename(executable)
    command_executable = executable.replace('$', '$$').replace("'", "$\\'")
    version = _version(json.loads(Path(package_json).read_text(encoding="utf-8"))["version"])
    file_version = build_identity(version, build_version, build_number, "windows")
    numeric = file_version.split("-", 1)[0].split("+", 1)[0].split(".")
    numeric += ["0"] * (4 - len(numeric))
    if len(set(protocols)) != len(protocols) or any(not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme) for scheme in protocols):
        raise ValueError("Invalid or duplicate protocol")
    associations = {}
    for extension, description in sorted((file_associations or {}).items()):
        if not re.fullmatch(r"\.[a-z0-9][a-z0-9_-]{0,31}", extension) or not description:
            raise ValueError("File associations require lowercase extensions and nonempty descriptions")
        literal(description)
        associations[extension] = ("RulesElectron." + hashlib.sha256((app_id + extension).encode()).hexdigest()[:24], description)
    app = Path(app)
    if compression not in ("7z", "zlib", "bzip2", "lzma", "off"):
        raise ValueError("Unsupported NSIS compressor")
    if architecture not in ("x64", "arm64"):
        raise ValueError("Unsupported Windows payload architecture")
    if updater_cache_name:
        _filename(updater_cache_name)
        literal(updater_cache_name)
        config = json.loads((app / 'resources/app-update.yml').read_text(encoding='utf-8'))
        if config.get('updaterCacheDirName') != updater_cache_name:
            raise ValueError('Installer updater cache must match app-update.yml')
    files = []
    directories = set()
    seen = set()
    for path in sorted(app.rglob("*")):
        if path.is_symlink():
            raise ValueError("Windows installer payload cannot contain symlinks")
        relative = path.relative_to(app)
        for part in relative.parts:
            _filename(part)
        name = relative.as_posix()
        literal(name)
        if name.casefold() in seen:
            raise ValueError("Case-insensitive Windows payload collision")
        seen.add(name.casefold())
        if path.is_dir():
            directories.add(name)
        elif path.is_file():
            files.append((name, path))
        else:
            raise ValueError("Windows installer requires regular payload files")
    if not any(name == executable for name, _ in files):
        raise ValueError("Windows app executable missing")
    if seen.intersection({"uninstall.exe", ".rules-electron.ini"}):
        raise ValueError("Runtime occupies installer-owned path")
    registry = "Software\\" + app_id
    uninstall_registry = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + app_id
    capabilities = registry + "\\Capabilities"
    registered_apps = "Software\\RegisteredApplications"
    q = literal
    lines = [
        '# -*- coding: utf-8 -*-', 'Unicode true', 'RequestExecutionLevel user',
        *(['SetCompress off'] if compression in ('7z', 'off') else ['SetCompressor /SOLID ' + compression]),
        *(['SetCompressorDictSize 8'] if compression == 'lzma' else []), 'SetDateSave off',
        '!include "FileFunc.nsh"', '!include "LogicLib.nsh"', '!include "x64.nsh"',
        'Name ' + q(product_name), 'OutFile ' + q(str(Path(output).resolve())),
        *(['Icon ' + q(str(Path(installer_icon).resolve()))] if installer_icon else []),
        *(['UninstallIcon ' + q(str(Path(uninstaller_icon).resolve()))] if uninstaller_icon else []),
        'InstallDir "$LOCALAPPDATA\\Programs\\' + app_id + '"',
        'VIProductVersion ' + '.'.join(numeric),
        'VIAddVersionKey "ProductName" ' + q(product_name),
        'VIAddVersionKey "FileDescription" ' + q(product_name + ' Installer'),
        'VIAddVersionKey "FileVersion" ' + q(file_version),
        'VIAddVersionKey "ProductVersion" ' + q(version),
        'VIAddVersionKey "LegalCopyright" ""',
        'Page directory', 'Page instfiles', 'UninstPage uninstConfirm', 'UninstPage instfiles',
    ]
    for prefix in ['', 'un.']:
        lines += [
            'Function ' + prefix + 'WaitForApp', 'StrCpy $R1 150',
            'wait:', 'nsProcess::_FindProcess ' + q(executable), 'Pop $R0',
            'StrCmp $R0 603 done', 'StrCmp $R0 0 0 failed',
            'Sleep 200', 'IntOp $R1 $R1 - 1', 'IntCmp $R1 0 failed wait wait',
            'failed:', 'SetErrorLevel 1', 'Abort "Close the application before continuing."',
            'done:', 'FunctionEnd',
        ]
    lines += [
        'Function .onInit', 'SetShellVarContext current', 'SetRegView 64',
        '${Unless} ${' + ('IsNativeARM64' if architecture == 'arm64' else 'IsNativeAMD64') + '}',
        'SetErrorLevel 1', 'Abort "Installer requires matching native Windows architecture."', '${EndUnless}',
        '${GetParameters} $0', 'ClearErrors', '${GetOptions} $0 "/D=" $1',
        'IfErrors registered_directory', 'StrCpy $INSTDIR $1', 'Goto initialized',
        'registered_directory:', 'ReadRegStr $0 HKCU ' + q(registry) + ' "InstallLocation"',
        'StrCmp $0 "" initialized', 'StrCpy $INSTDIR $0', 'initialized:', 'ClearErrors',
        'FunctionEnd', 'Function un.onInit', 'SetShellVarContext current', 'SetRegView 64',
        'ReadINIStr $0 "$INSTDIR\\.rules-electron.ini" "app" "id"',
        'StrCmp $0 ' + q(app_id) + ' +3', 'SetErrorLevel 1', 'Abort "Installation ownership mismatch."',
        'Call un.WaitForApp', 'FunctionEnd', 'Section "Install"', 'Call WaitForApp',
    ]
    for index, scheme in enumerate(protocols):
        key = 'Software\\Classes\\' + scheme
        lines += [
            'ReadRegStr $0 HKCU ' + q(key) + ' "RulesElectronOwner"',
            'StrCmp $0 ' + q(app_id) + ' protocol_ok_' + str(index),
            'ClearErrors', 'EnumRegValue $1 HKCU ' + q(key) + ' 0',
            'IfErrors protocol_subkey_' + str(index),
            'SetErrorLevel 1', 'Abort "Protocol already registered by another application."',
            'protocol_subkey_' + str(index) + ':',
            'ClearErrors', 'EnumRegKey $1 HKCU ' + q(key) + ' 0',
            'IfErrors protocol_ok_' + str(index),
            'SetErrorLevel 1', 'Abort "Protocol already registered by another application."',
            'protocol_ok_' + str(index) + ':',
        ]
    if associations:
        lines += ['ReadRegStr $0 HKCU ' + q(registered_apps) + ' ' + q(app_id),
                  'StrCmp $0 "" file_registration_ok',
                  'StrCmp $0 ' + q(capabilities) + ' file_registration_ok',
                  'SetErrorLevel 1', 'Abort "Application capabilities already registered by another application."',
                  'file_registration_ok:']
    for index, (progid, _) in enumerate(associations.values()):
        key = 'Software\\Classes\\' + progid
        suffix = str(index)
        lines += ['ReadRegStr $0 HKCU ' + q(key) + ' "RulesElectronOwner"',
                  'StrCmp $0 ' + q(app_id) + ' file_type_ok_' + suffix,
                  'ClearErrors', 'EnumRegValue $1 HKCU ' + q(key) + ' 0',
                  'IfErrors file_type_subkey_' + suffix,
                  'SetErrorLevel 1', 'Abort "File type already registered by another application."',
                  'file_type_subkey_' + suffix + ':', 'ClearErrors',
                  'EnumRegKey $1 HKCU ' + q(key) + ' 0', 'IfErrors file_type_ok_' + suffix,
                  'SetErrorLevel 1', 'Abort "File type already registered by another application."',
                  'file_type_ok_' + suffix + ':']
    if updater_cache_name:
        cache = '$LOCALAPPDATA\\' + updater_cache_name.replace('$', '$$')
        lines += ['ReadINIStr $0 "' + cache + '\\.rules-electron.ini" "app" "id"',
                  'StrCmp $0 ' + q(app_id) + ' cache_owned',
                  'IfFileExists "' + cache + '\\.rules-electron.ini" cache_conflict',
                  'IfFileExists "' + cache + '\\installer.exe" 0 cache_owned',
                  'cache_conflict:', 'SetErrorLevel 1', 'Abort "Updater cache ownership mismatch."', 'cache_owned:']
    lines += [
        'IfFileExists "$INSTDIR\\.rules-electron.ini" existing fresh',
        'existing:', 'ReadINIStr $0 "$INSTDIR\\.rules-electron.ini" "app" "id"',
        'StrCmp $0 ' + q(app_id) + ' owned', 'SetErrorLevel 1', 'Abort "Installation ownership mismatch."',
        'owned:', 'IfFileExists "$INSTDIR\\Uninstall.exe" 0 failed_install',
        'ClearErrors', 'ExecWait \'"$INSTDIR\\Uninstall.exe" /S _?=$INSTDIR\' $0',
        'IfErrors failed_install', 'StrCmp $0 0 unpack failed_install',
        'fresh:', 'FindFirst $0 $1 "$INSTDIR\\*.*"', 'check_empty:',
        'StrCmp $1 "" empty', 'StrCmp $1 "." next', 'StrCmp $1 ".." next',
        'FindClose $0', 'SetErrorLevel 1', 'Abort "Refusing to overwrite an unowned directory."',
        'next:', 'FindNext $0 $1', 'Goto check_empty', 'empty:', 'FindClose $0',
        'unpack:', 'SetOverwrite try', 'ClearErrors',
    ]
    if compression == '7z':
        lines += ['InitPluginsDir', 'SetOutPath "$PLUGINSDIR"',
                  'File "/oname=payload.7z" ' + q(str(Path(payload_archive).resolve())),
                  'IfErrors failed_install', 'SetOutPath "$INSTDIR"',
                  'Nsis7z::Extract "$PLUGINSDIR\\payload.7z"']
        for name in sorted(directories):
            lines += ['CreateDirectory "$INSTDIR\\' + name.replace('/', '\\').replace('$', '$$') + '"', 'IfErrors failed_install']
        for name, path in files:
            target = '"$INSTDIR\\' + name.replace('/', '\\').replace('$', '$$') + '"'
            lines += ['ClearErrors', 'FileOpen $0 ' + target + ' r', 'IfErrors failed_install',
                      'FileSeek $0 0 END $1', 'FileClose $0',
                      'IntCmp $1 ' + str(path.stat().st_size) + ' +2', 'Goto failed_install']
    else:
        for name, path in files:
            parent = str(Path(name).parent).replace('/', '\\').replace('$', '$$')
            lines += ['SetOutPath "$INSTDIR' + ('\\' + parent if parent != '.' else '') + '"',
                      'File ' + q('/oname=' + Path(name).name) + ' ' + q(str(path.resolve())),
                      'IfErrors failed_install']
    lines += [
        'SetOutPath "$INSTDIR"', 'WriteUninstaller "$INSTDIR\\Uninstall.exe"',
        'WriteINIStr "$INSTDIR\\.rules-electron.ini" "app" "id" ' + q(app_id),
        'WriteRegStr HKCU ' + q(registry) + ' "InstallLocation" "$INSTDIR"',
        'WriteRegStr HKCU ' + q(uninstall_registry) + ' "InstallLocation" "$INSTDIR"',
        'WriteRegStr HKCU ' + q(uninstall_registry) + ' "DisplayName" ' + q(product_name),
        'WriteRegStr HKCU ' + q(uninstall_registry) + ' "UninstallString" \'"$INSTDIR\\Uninstall.exe"\'',
        'WriteRegStr HKCU ' + q(uninstall_registry) + ' "QuietUninstallString" \'"$INSTDIR\\Uninstall.exe" /S\'',
        'WriteRegDWORD HKCU ' + q(uninstall_registry) + ' "NoModify" 1',
        'WriteRegDWORD HKCU ' + q(uninstall_registry) + ' "NoRepair" 1',
        'CreateShortcut "$SMPROGRAMS\\' + product_name.replace('$', '$$') + '.lnk" "$INSTDIR\\' + executable.replace('$', '$$') + '"',
        'IfErrors failed_install',
        'WinShell::SetLnkAUMI "$SMPROGRAMS\\' + product_name.replace('$', '$$') + '.lnk" ' + q(app_user_model_id),
    ]
    if desktop_shortcut:
        lines += ['CreateShortcut "$DESKTOP\\' + product_name.replace('$', '$$') + '.lnk" "$INSTDIR\\' + executable.replace('$', '$$') + '"',
                  'IfErrors failed_install',
                  'WinShell::SetLnkAUMI "$DESKTOP\\' + product_name.replace('$', '$$') + '.lnk" ' + q(app_user_model_id)]
    for scheme in protocols:
        key = 'Software\\Classes\\' + scheme
        lines += ['WriteRegStr HKCU ' + q(key) + ' "" ' + q('URL:' + product_name),
                  'WriteRegStr HKCU ' + q(key) + ' "URL Protocol" ""',
                  'WriteRegStr HKCU ' + q(key) + ' "RulesElectronOwner" ' + q(app_id),
                  'WriteRegStr HKCU ' + q(key + '\\shell\\open\\command') + ' "" \'"$INSTDIR\\' + command_executable + '" "%1"\'']
    if associations:
        lines += ['WriteRegStr HKCU ' + q(capabilities) + ' "ApplicationName" ' + q(product_name),
                  'WriteRegStr HKCU ' + q(capabilities) + ' "ApplicationDescription" ' + q(product_name),
                  'WriteRegStr HKCU ' + q(registered_apps) + ' ' + q(app_id) + ' ' + q(capabilities)]
    for extension, (progid, description) in associations.items():
        key = 'Software\\Classes\\' + progid
        lines += ['WriteRegStr HKCU ' + q(key) + ' "" ' + q(description),
                  'WriteRegStr HKCU ' + q(key) + ' "RulesElectronOwner" ' + q(app_id),
                  'WriteRegStr HKCU ' + q(key + '\\DefaultIcon') + ' "" \'"$INSTDIR\\' + command_executable + '",0\'',
                  'WriteRegStr HKCU ' + q(key + '\\shell\\open\\command') + ' "" \'"$INSTDIR\\' + command_executable + '" "%1"\'',
                  'WriteRegStr HKCU ' + q('Software\\Classes\\' + extension + '\\OpenWithProgids') + ' ' + q(progid) + ' ""',
                  'WriteRegStr HKCU ' + q(capabilities + '\\FileAssociations') + ' ' + q(extension) + ' ' + q(progid)]
    if associations:
        lines += ["System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0) v'"]
    if updater_cache_name:
        lines += ['CreateDirectory "' + cache + '"',
                  'StrCmp $EXEPATH "' + cache + '\\installer.exe" seeded',
                  'CopyFiles /SILENT "$EXEPATH" "' + cache + '\\installer.exe"',
                  'seeded:',
                  'WriteINIStr "' + cache + '\\.rules-electron.ini" "app" "id" ' + q(app_id)]
    lines += ['IfErrors failed_install',
              'WriteRegStr HKCU ' + q(uninstall_registry) + ' "DisplayVersion" ' + q(version),
              'IfErrors failed_install', 'SetErrorLevel 0', 'Goto installed',
              'failed_install:', 'SetErrorLevel 1', 'Abort "Installation failed."', 'installed:',
              '${GetParameters} $0', 'ClearErrors', '${GetOptions} $0 "--force-run" $1',
              'IfErrors no_launch', 'Exec \'"$INSTDIR\\' + command_executable + '"\'',
              'no_launch:', 'SectionEnd', 'Section "Uninstall"', 'ClearErrors']
    for name, _ in files:
        lines += ['Delete "$INSTDIR\\' + name.replace('/', '\\').replace('$', '$$') + '"']
    lines += ['IfErrors uninstall_failed', 'Delete "$INSTDIR\\Uninstall.exe"', 'Delete "$INSTDIR\\.rules-electron.ini"',
              'DeleteRegKey HKCU ' + q(registry), 'DeleteRegKey HKCU ' + q(uninstall_registry),
              'Delete "$SMPROGRAMS\\' + product_name.replace('$', '$$') + '.lnk"']
    if desktop_shortcut:
        lines += ['Delete "$DESKTOP\\' + product_name.replace('$', '$$') + '.lnk"']
    for index, scheme in enumerate(protocols):
        key = 'Software\\Classes\\' + scheme
        lines += ['ReadRegStr $0 HKCU ' + q(key) + ' "RulesElectronOwner"',
                  'StrCmp $0 ' + q(app_id) + ' 0 un_protocol_' + str(index),
                  'ReadRegStr $0 HKCU ' + q(key + '\\shell\\open\\command') + ' ""',
                  'StrCmp $0 \'"$INSTDIR\\' + command_executable + '" "%1"\' 0 un_protocol_' + str(index),
                  'DeleteRegKey HKCU ' + q(key), 'un_protocol_' + str(index) + ':']
    for index, (extension, (progid, _)) in enumerate(associations.items()):
        key = 'Software\\Classes\\' + progid
        extension_key = 'Software\\Classes\\' + extension
        suffix = str(index)
        lines += ['ReadRegStr $0 HKCU ' + q(key) + ' "RulesElectronOwner"',
                  'StrCmp $0 ' + q(app_id) + ' 0 un_file_type_' + suffix,
                  'ReadRegStr $0 HKCU ' + q(key + '\\shell\\open\\command') + ' ""',
                  'StrCmp $0 \'"$INSTDIR\\' + command_executable + '" "%1"\' 0 un_file_type_' + suffix,
                  'DeleteRegValue HKCU ' + q(extension_key + '\\OpenWithProgids') + ' ' + q(progid),
                  'DeleteRegKey /ifempty HKCU ' + q(extension_key + '\\OpenWithProgids'),
                  'DeleteRegKey /ifempty HKCU ' + q(extension_key),
                  'DeleteRegKey HKCU ' + q(key), 'un_file_type_' + suffix + ':']
    if associations:
        lines += ['ReadRegStr $0 HKCU ' + q(registered_apps) + ' ' + q(app_id),
                  'StrCmp $0 ' + q(capabilities) + ' 0 un_file_registration',
                  'DeleteRegValue HKCU ' + q(registered_apps) + ' ' + q(app_id),
                  'un_file_registration:', "System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0) v'"]
    for name in sorted(directories, key=lambda n: (-n.count('/'), n)):
        lines += ['RMDir "$INSTDIR\\' + name.replace('/', '\\').replace('$', '$$') + '"']
    lines += ['RMDir "$INSTDIR"', 'SetErrorLevel 0', 'Goto uninstalled',
              'uninstall_failed:', 'SetErrorLevel 1', 'Abort "Unable to remove application files."',
              'uninstalled:', 'SectionEnd']
    return '\n'.join(lines) + '\n'


def build_installer(manifest, output, script):
    manifest = dict(manifest)
    compiler = str(Path(manifest.pop('compiler')).resolve())
    data = str(Path(manifest.pop('data')).resolve())
    verify = manifest.pop('verify_reproducible', False)
    archive_compiler = manifest.pop('archive_compiler', '')
    if archive_compiler:
        archive_compiler = str(Path(archive_compiler).resolve())
    executable = manifest['executable_name']
    if not executable.endswith('.exe'):
        executable += '.exe'
    with (Path(manifest['app']) / executable).open('rb') as source:
        header = source.read(64)
        if len(header) < 64 or header[:2] != b'MZ':
            raise ValueError('NSIS payload requires a Windows PE executable')
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset > 1024**2:
            raise ValueError('Invalid PE header offset')
        source.seek(offset)
        pe = source.read(6)
        if len(pe) != 6 or pe[:4] != b'PE\0\0' or struct.unpack_from('<H', pe, 4)[0] != {'x64': 0x8664, 'arm64': 0xaa64}[manifest['architecture']]:
            raise ValueError('NSIS payload architecture mismatch')
    output = Path(output).resolve()
    environment = {'NSISDIR': data, 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC', 'SOURCE_DATE_EPOCH': '0'}

    def compile_once(options, directory, destination, script_path):
        options = dict(options)
        if options.get('compression') == '7z':
            if not archive_compiler:
                raise ValueError('7z compression requires a declared archive compiler')
            payload = directory / 'payload.7z'
            options['payload_archive'] = str(payload)
            installer_script(output=destination, **options)
            listing = directory / 'files.txt'
            app = Path(options['app']).resolve()
            listing.write_text(''.join(path.relative_to(app).as_posix() + '\n' for path in sorted(app.rglob('*')) if path.is_file()), encoding='utf-8')
            subprocess.run([archive_compiler, 'a', '-t7z', '-mx=5', '-m0=LZMA2:d1m', '-mf=off', '-mmt=2', '-ms=off',
                            '-mtc=off', '-mta=off', '-mtm=off', '-scsUTF-8', '-bd', '-bso0', '-bsp0',
                            str(payload), '@' + str(listing)], cwd=app, env=environment, check=True)
            methods = subprocess.run([archive_compiler, 'l', '-slt', str(payload)], env=environment,
                                     capture_output=True, text=True, check=True).stdout
            selected = {line.removeprefix('Method = ').strip() for line in methods.splitlines() if line.startswith('Method = ')}
            if any(any(not (part == 'Copy' or part.startswith('LZMA2')) for part in method.split()) for method in selected):
                raise ValueError('NSIS payload requires plain LZMA2 or Copy streams: ' + repr(sorted(selected)))
        text = installer_script(output=destination, **options)
        script_path.write_text(text, encoding='utf-8')
        subprocess.run([compiler, '-NOCONFIG', '-V2', str(script_path.resolve())], env=environment, check=True)

    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        compile_once(manifest, directory, output, Path(script))
        if verify:
            mirror = Path(directory) / 'payload'
            shutil.copytree(manifest['app'], mirror)
            for path in mirror.rglob('*'):
                if path.is_file():
                    os.utime(path, (1234567890, 1234567890))
            repeat = directory / 'repeat'
            repeat.mkdir()
            second = repeat / output.name
            compile_once(dict(manifest, app=str(mirror)), repeat, second, repeat / 'installer.nsi')
            def digest(path):
                with path.open('rb') as source:
                    return hashlib.file_digest(source, 'sha256').digest()
            if digest(output) != digest(second):
                raise ValueError('NSIS output is not reproducible across output directories')


if __name__ == '__main__':
    build_installer(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2], sys.argv[3])
