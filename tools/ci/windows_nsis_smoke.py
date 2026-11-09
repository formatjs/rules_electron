"""Install, reject corruption, update differentially and uninstall on native Windows."""

from functools import partial
import csv
import ctypes
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit
import winreg

from windows_installer_trace import installer_trace

APP_ID = "org.example.sample-desktop"
REGISTRY = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APP_ID
PROTOCOL = r"Software\Classes\sample-desktop"
EXTENSIONS = [".rules-electron-sample", ".rules-electron-cleanup"]
CAPABILITIES = "Software\\" + APP_ID + "\\Capabilities"
REGISTERED_APPS = r"Software\RegisteredApplications"


def registry_value(key, name, root=winreg.HKEY_CURRENT_USER):
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except FileNotFoundError:
        return None


def registry_exists(key, root=winreg.HKEY_CURRENT_USER):
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except FileNotFoundError:
        return False


def file_handlers(executable, architecture, root=winreg.HKEY_CURRENT_USER):
    value = partial(registry_value, root=root)
    assert value(REGISTERED_APPS, APP_ID) == CAPABILITIES
    query = ctypes.windll.shlwapi.AssocQueryStringW
    query.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p,
                      ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint)]
    query.restype = ctypes.c_long
    handlers = []
    for extension in EXTENSIONS:
        progid = value(CAPABILITIES + r"\FileAssociations", extension)
        assert isinstance(progid, str) and progid.startswith("RulesElectron.")
        key = "Software\\Classes\\" + progid
        assert value(key, "RulesElectronOwner") == APP_ID
        document_icon = executable.parent / "resources/document.ico" if extension == EXTENSIONS[0] else executable
        expected_icon = f'"{document_icon}",0'
        assert value(key + r"\DefaultIcon", "") == expected_icon
        resolved_icon = ctypes.create_unicode_buffer(32768)
        icon_size = ctypes.c_uint(len(resolved_icon))
        # ASSOCSTR_DEFAULTICON; same fixed ProgID flags as command lookup.
        assert query(0x2800, 15, progid, None, resolved_icon, ctypes.byref(icon_size)) == 0
        assert resolved_icon.value == expected_icon
        if extension == EXTENSIONS[0]:
            icon(document_icon, architecture, 83)
        assert value("Software\\Classes\\" + extension + r"\OpenWithProgids", progid) == ""
        command = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_uint(len(command))
        # ASSOCF_INIT_FIXED_PROGID | ASSOCF_INIT_FOR_FILE, ASSOCSTR_COMMAND.
        assert query(0x2800, 1, progid, "open", command, ctypes.byref(size)) == 0
        assert command.value == f'"{executable}" "%1"'
        handlers.append(progid)
    assert value("Software\\Classes\\" + EXTENSIONS[0], "") == "Foreign.Document"
    return handlers


def known_folder(identifier):
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, identifier, None, 0, buffer):
        raise RuntimeError("Cannot resolve Windows shell folder")
    return Path(buffer.value)


def command(*args, env=None, success=True, nsis_directory=None):
    # NSIS requires /D last and unquoted, including paths containing spaces.
    arguments = subprocess.list2cmdline(args) + " /D=" + str(nsis_directory) if nsis_directory else args
    result = subprocess.run(arguments, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    if (result.returncode == 0) != success:
        raise RuntimeError(f"Unexpected exit {result.returncode}: {args}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
    return result.stdout


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").digest()


def wait_for(predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError("Windows installer state did not converge")
        time.sleep(0.25)


def update_failure_state(install, cache):
    processes = {}
    tasklist = Path(os.environ["SystemRoot"]) / "System32/tasklist.exe"
    for name in ("sample-desktop.exe", "Sample-2.0.0.exe", "installer.exe", "Uninstall.exe"):
        result = subprocess.run([str(tasklist), "/FI", "IMAGENAME eq " + name, "/FO", "CSV", "/NH"],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        processes[name] = sum(bool(row) and row[0].casefold() == name.casefold()
                              for row in csv.reader(result.stdout.splitlines())) if result.returncode == 0 else None
    version = registry_value(REGISTRY, "DisplayVersion")
    print("NSIS_UPDATE_FAILURE_STATE " + json.dumps({
        "registered_version": version if version in (None, "1.0.0", "2.0.0") else "other",
        "installed_executable": (install / "sample-desktop.exe").is_file(),
        "ownership_marker": (install / ".rules-electron.ini").is_file(),
        "uninstaller": (install / "Uninstall.exe").is_file(),
        "cached_installer": (cache / "installer.exe").is_file(),
        "pending_installers": len(list((cache / "pending").glob("*.exe"))),
        "process_counts": processes,
    }, sort_keys=True), flush=True)


class FeedHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        name = unquote(urlsplit(self.path).path).lstrip("/")
        file = (Path(self.directory) / name).resolve()
        if not file.is_relative_to(Path(self.directory).resolve()):
            self.send_error(404)
            return
        if file.suffix != ".exe":
            super().do_GET()
            return
        size = file.stat().st_size
        ranges = self.headers.get("Range")
        if ranges:
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", ranges)
            if not match or not 0 <= int(match[1]) <= int(match[2]) < size:
                self.send_error(416)
                return
            start, end = map(int, match.groups())
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            start, end = 0, size - 1
            self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with self.server.lock:
            self.server.transfers.append((bool(ranges), end - start + 1))
        with file.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                data = source.read(min(1024**2, remaining))
                if self.server.corrupt and source.tell() - len(data) == 0:
                    data = bytes([data[0] ^ 1]) + data[1:]
                self.wfile.write(data)
                remaining -= len(data)


def smoke(executable, architecture, expected, shortcuts=None):
    shortcuts = shortcuts if shortcuts is not None else [known_folder(2) / "Sample Desktop.lnk", known_folder(16) / "Sample Desktop.lnk"]
    print(command(sys.executable, "examples/desktop/tools/smoke_test.py", str(executable),
                  "--installed", "--expected-version", expected,
                  "--target-os", "windows", "--target-arch", architecture,
                  *[value for shortcut in shortcuts for value in ["--shortcut", str(shortcut)]]), flush=True)


def icon(executable, architecture, gray):
    print(command(sys.executable, "examples/desktop/tools/smoke_test.py", str(executable),
                  "--icon-only", "--icon-gray", str(gray),
                  "--target-os", "windows", "--target-arch", architecture), flush=True)


if __name__ == "__main__":
    packages = Path(sys.argv[1]).resolve()
    architecture = sys.argv[2]
    native = {"amd64": "x64", "arm64": "arm64"}.get(platform.machine().lower())
    if platform.system() != "Windows" or native != architecture:
        raise RuntimeError("NSIS smoke requires the matching native Windows host")
    ctypes.windll.kernel32.SetErrorMode(0x8003)
    cache = Path(os.environ["LOCALAPPDATA"]) / "sample-desktop-updater"
    user_data = Path(os.environ["APPDATA"]) / "Sample Desktop"
    shortcuts = [known_folder(2) / "Sample Desktop.lnk", known_folder(16) / "Sample Desktop.lnk"]
    existing = {
        "uninstall registry": registry_exists(REGISTRY),
        "app registry": registry_exists("Software\\" + APP_ID),
        "protocol": registry_exists(PROTOCOL), "updater cache": cache.exists(),
        "app data": user_data.exists(), "shortcuts": any(p.exists() for p in shortcuts),
        "file associations": any(registry_exists("Software\\Classes\\" + extension) for extension in EXTENSIONS),
        "registered application": registry_value(REGISTERED_APPS, APP_ID) is not None,
    }
    if any(existing.values()):
        raise RuntimeError("Disposable host already contains sample state: " + ", ".join(k for k, v in existing.items() if v))
    first = packages / "nsis_v1_feed/Sample-1.0.0.exe"
    second = packages / "nsis_v2_feed/Sample-2.0.0.exe"
    icon(first, architecture, 73)
    icon(second, architecture, 73)
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        install = directory / "Installed Sample Desktop"
        executable = install / "sample-desktop.exe"
        feed = directory / "feed"
        feed.mkdir()
        for source in [packages / "nsis_v1_feed", packages / "nsis_v2_feed"]:
            for file in source.iterdir():
                shutil.copyfile(file, feed / file.name)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=str(feed)))
        server.corrupt, server.transfers, server.lock = True, [], threading.Lock()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        environment = dict(os.environ, RULES_ELECTRON_UPDATE_FEED=f"http://127.0.0.1:{server.server_port}/")
        try:
            unowned = directory / "unowned"
            unowned.mkdir()
            (unowned / "keep.txt").write_text("keep")
            command(str(first), "/S", nsis_directory=unowned, success=False)
            assert list(unowned.iterdir()) == [unowned / "keep.txt"]
            assert (unowned / "keep.txt").read_text() == "keep"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PROTOCOL) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "foreign registration")
            command(str(first), "/S", nsis_directory=install, success=False)
            assert registry_value(PROTOCOL, "") == "foreign registration"
            assert not executable.exists()
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, PROTOCOL)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTERED_APPS) as key:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, "Software\\Foreign\\Capabilities")
            command(str(first), "/S", nsis_directory=install, success=False)
            assert registry_value(REGISTERED_APPS, APP_ID) == "Software\\Foreign\\Capabilities"
            assert not executable.exists()
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTERED_APPS, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_ID)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\Classes\\" + EXTENSIONS[0]) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Foreign.Document")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\Classes\\" + EXTENSIONS[0] + r"\OpenWithProgids") as key:
                winreg.SetValueEx(key, "Foreign.Document", 0, winreg.REG_SZ, "")
            command(str(first), "/S", nsis_directory=install)
            assert registry_value(REGISTRY, "DisplayVersion") == "1.0.0"
            assert registry_value(REGISTRY, "InstallLocation") == str(install)
            assert registry_value(REGISTRY, "QuietUninstallString") == f'"{install}\\Uninstall.exe" /S'
            assert registry_value(PROTOCOL + r"\shell\open\command", "") == f'"{executable}" "%1"'
            assert all(p.is_file() for p in shortcuts)
            handlers = file_handlers(executable, architecture)
            icon(install / "Uninstall.exe", architecture, 113)
            assert digest(cache / "installer.exe") == digest(first)
            smoke(executable, architecture, "1.0.0")
            (install / "keep-user-data.txt").write_text("keep")
            rejected = command(str(executable), "--reject-update-smoke", "--disable-gpu", "--user-data-dir=" + str(directory / "update-profile"), env=environment)
            assert "UPDATE_HASH_REJECTED" in rejected, rejected
            assert registry_value(REGISTRY, "DisplayVersion") == "1.0.0"
            assert digest(cache / "installer.exe") == digest(first)
            with server.lock:
                server.corrupt = False
                server.transfers.clear()
            with installer_trace(directory) as installer_completed:
                updated = command(str(executable), "--install-update-smoke", "--disable-gpu", "--user-data-dir=" + str(directory / "update-profile"), env=environment)
                assert "INSTALLED_UPDATE_SMOKE_OK" in updated, updated
                assert "Cannot download differentially" not in updated, updated
                try:
                    wait_for(lambda: registry_value(REGISTRY, "DisplayVersion") == "2.0.0")
                    wait_for(installer_completed, timeout=30)
                except RuntimeError:
                    update_failure_state(install, cache)
                    raise
            assert registry_value(REGISTRY, "InstallLocation") == str(install)
            assert server.transfers and all(ranged for ranged, _ in server.transfers), server.transfers
            transferred = sum(size for _, size in server.transfers)
            assert transferred < second.stat().st_size // 2, (transferred, second.stat().st_size)
            assert digest(cache / "installer.exe") == digest(second)
            assert (install / "keep-user-data.txt").read_text() == "keep"
            assert file_handlers(executable, architecture) == handlers
            icon(install / "Uninstall.exe", architecture, 113)
            smoke(executable, architecture, "2.0.0")
            command(str(install / "Uninstall.exe"), "/S")
            wait_for(lambda: registry_value(REGISTRY, "DisplayVersion") is None and not executable.exists() and not (install / "Uninstall.exe").exists())
            assert registry_value(PROTOCOL, "") is None
            assert all(not p.exists() for p in shortcuts)
            assert registry_value(REGISTERED_APPS, APP_ID) is None
            assert all(not registry_exists("Software\\Classes\\" + progid) for progid in handlers)
            assert not registry_exists("Software\\Classes\\" + EXTENSIONS[1])
            assert registry_value("Software\\Classes\\" + EXTENSIONS[0], "") == "Foreign.Document"
            assert registry_value("Software\\Classes\\" + EXTENSIONS[0] + r"\OpenWithProgids", "Foreign.Document") == ""
            assert sorted(p.relative_to(install).as_posix() for p in install.rglob("*")) == ["keep-user-data.txt"]
            assert (install / "keep-user-data.txt").read_text() == "keep"
            print(f"NSIS_UPDATE_SMOKE_OK architecture={architecture} range_bytes={transferred} installer_bytes={second.stat().st_size}", flush=True)
        finally:
            server.shutdown()
            server.server_close()
            if (install / "Uninstall.exe").exists():
                command(str(install / "Uninstall.exe"), "/S")
                wait_for(lambda: not (install / "Uninstall.exe").exists())
            for path in [cache, user_data]:
                if path.exists():
                    shutil.rmtree(path)
            for extension in EXTENSIONS:
                key = "Software\\Classes\\" + extension
                if registry_exists(key + r"\OpenWithProgids"):
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key + r"\OpenWithProgids")
                if registry_exists(key):
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
