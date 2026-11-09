"""Real machine-scope Electron install/update/removal on disposable Windows."""

import ctypes
from functools import partial
import http.server
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import threading
import winreg

from windows_installer_trace import installer_trace
from windows_nsis_smoke import (
    APP_ID, CAPABILITIES, EXTENSIONS, FeedHandler, PROTOCOL, REGISTERED_APPS, REGISTRY,
    command, digest, file_handlers, known_folder, registry_exists, registry_value, smoke, wait_for,
)


def main():
    packages, architecture = Path(sys.argv[1]).resolve(), sys.argv[2]
    if (platform.system() != "Windows" or not ctypes.windll.shell32.IsUserAnAdmin()
            or {"amd64": "x64", "arm64": "arm64"}.get(platform.machine().lower()) != architecture):
        raise RuntimeError("Machine NSIS smoke requires matching elevated disposable host")
    value = partial(registry_value, root=winreg.HKEY_LOCAL_MACHINE)
    exists = partial(registry_exists, root=winreg.HKEY_LOCAL_MACHINE)
    cache = Path(os.environ["LOCALAPPDATA"]) / "sample-desktop-updater"
    user_data = Path(os.environ["APPDATA"]) / "Sample Desktop"
    install = Path(os.environ.get("ProgramW6432", os.environ["ProgramFiles"])) / APP_ID
    executable = install / "sample-desktop.exe"
    shortcuts = [known_folder(23) / "Sample Desktop.lnk", known_folder(25) / "Sample Desktop.lnk"]
    if (install.exists() or cache.exists() or user_data.exists() or exists(REGISTRY)
            or exists("Software\\" + APP_ID) or exists(PROTOCOL)
            or registry_exists("Software\\" + APP_ID) or registry_exists(REGISTRY)
            or any(p.exists() for p in shortcuts)
            or any(exists("Software\\Classes\\" + extension) for extension in EXTENSIONS)
            or value(REGISTERED_APPS, APP_ID) is not None):
        raise RuntimeError("Disposable host already contains machine fixture state")
    helper = packages / "windows_elevate.exe"
    first = packages / "nsis_machine_v1_feed/Sample-1.0.0.exe"
    second = packages / "nsis_machine_v2_feed/Sample-2.0.0.exe"
    with tempfile.TemporaryDirectory(prefix="machine-nsis-") as temporary:
        temporary = Path(temporary)
        feed = temporary / "feed"
        feed.mkdir()
        for source in (packages / "nsis_machine_v1_feed", packages / "nsis_machine_v2_feed"):
            for file in source.iterdir():
                shutil.copyfile(file, feed / file.name)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(FeedHandler, directory=str(feed)))
        server.corrupt, server.transfers, server.lock = True, [], threading.Lock()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        environment = dict(os.environ, RULES_ELECTRON_UPDATE_FEED=f"http://127.0.0.1:{server.server_port}/",
                           RULES_ELECTRON_EXPECT_ADMIN_UPDATE="1")
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\" + APP_ID) as key:
                winreg.SetValueEx(key, "ScopeSentinel", 0, winreg.REG_SZ, "keep-current-user")
            wrong_scope = temporary / "user-owned"
            wrong_scope.mkdir()
            (wrong_scope / ".rules-electron.ini").write_text("[app]\nid=" + APP_ID + "\nscope=user\n")
            (wrong_scope / "keep.txt").write_text("keep")
            command(str(helper), "--wait", str(first), "/S", nsis_directory=wrong_scope, success=False)
            assert (wrong_scope / "keep.txt").read_text() == "keep"
            assert value(REGISTRY, "DisplayVersion") is None
            for extension in EXTENSIONS[:1]:
                with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, "Software\\Classes\\" + extension) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Foreign.Document")
                with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, "Software\\Classes\\" + extension + r"\OpenWithProgids") as key:
                    winreg.SetValueEx(key, "Foreign.Document", 0, winreg.REG_SZ, "")
            command(str(helper), "--wait", str(first), "/S")
            assert value(REGISTRY, "DisplayVersion") == "1.0.0"
            assert Path(value(REGISTRY, "InstallLocation")) == install
            assert registry_value(REGISTRY, "DisplayVersion") is None
            assert registry_value("Software\\" + APP_ID, "ScopeSentinel") == "keep-current-user"
            assert value(PROTOCOL + r"\shell\open\command", "") == f'"{executable}" "%1"'
            assert all(path.is_file() for path in shortcuts)
            assert digest(install / "resources/elevate.exe") == digest(helper)
            assert not (cache / "installer.exe").exists()
            handlers = file_handlers(executable, architecture, root=winreg.HKEY_LOCAL_MACHINE)
            smoke(executable, architecture, "1.0.0", shortcuts=shortcuts)
            (install / "keep-user-data.txt").write_text("keep")
            rejected = command(str(executable), "--reject-update-smoke", "--disable-gpu",
                               "--user-data-dir=" + str(temporary / "update-profile"), env=environment)
            assert "UPDATE_HASH_REJECTED" in rejected
            assert value(REGISTRY, "DisplayVersion") == "1.0.0"
            with server.lock:
                server.corrupt = False
                server.transfers.clear()
            with installer_trace(temporary) as completed:
                updated = command(str(executable), "--install-update-smoke", "--disable-gpu",
                                  "--user-data-dir=" + str(temporary / "update-profile"), env=environment)
                assert "INSTALLED_UPDATE_SMOKE_OK" in updated
                assert "isAdminRightsRequired is set to true" in updated
                wait_for(lambda: value(REGISTRY, "DisplayVersion") == "2.0.0")
                wait_for(completed, timeout=30)
            assert Path(value(REGISTRY, "InstallLocation")) == install
            assert registry_value(REGISTRY, "DisplayVersion") is None
            assert registry_value("Software\\" + APP_ID, "ScopeSentinel") == "keep-current-user"
            assert server.transfers and any(not ranged for ranged, _ in server.transfers)
            assert (install / "keep-user-data.txt").read_text() == "keep"
            assert file_handlers(executable, architecture, root=winreg.HKEY_LOCAL_MACHINE) == handlers
            smoke(executable, architecture, "2.0.0", shortcuts=shortcuts)
            marker = install / ".rules-electron.ini"
            write = ctypes.windll.kernel32.WritePrivateProfileStringW
            write.argtypes, write.restype = [ctypes.c_wchar_p] * 4, ctypes.c_int
            assert write("app", "scope", "user", str(marker))
            command(str(install / "Uninstall.exe"), "/S", nsis_uninstall_directory=install, success=False)
            assert executable.is_file() and value(REGISTRY, "DisplayVersion") == "2.0.0"
            assert write("app", "scope", "machine", str(marker))
            command(str(helper), "--wait", str(install / "Uninstall.exe"), "/S")
            wait_for(lambda: value(REGISTRY, "DisplayVersion") is None and not executable.exists()
                     and not (install / "Uninstall.exe").exists())
            assert value(PROTOCOL, "") is None
            assert value(REGISTERED_APPS, APP_ID) is None
            assert all(not exists("Software\\Classes\\" + progid) for progid in handlers)
            assert not exists("Software\\Classes\\" + EXTENSIONS[1])
            assert value("Software\\Classes\\" + EXTENSIONS[0], "") == "Foreign.Document"
            assert value("Software\\Classes\\" + EXTENSIONS[0] + r"\OpenWithProgids", "Foreign.Document") == ""
            assert all(not path.exists() for path in shortcuts)
            assert sorted(path.relative_to(install).as_posix() for path in install.rglob("*")) == ["keep-user-data.txt"]
            assert registry_value("Software\\" + APP_ID, "ScopeSentinel") == "keep-current-user"
            print("NSIS_MACHINE_UPDATE_SMOKE_OK architecture=" + architecture, flush=True)
        finally:
            server.shutdown()
            server.server_close()
            if (install / "Uninstall.exe").exists():
                write = ctypes.windll.kernel32.WritePrivateProfileStringW
                write.argtypes = [ctypes.c_wchar_p] * 4
                write("app", "scope", "machine", str(install / ".rules-electron.ini"))
                command(str(helper), "--wait", str(install / "Uninstall.exe"), "/S")
                wait_for(lambda: not (install / "Uninstall.exe").exists())
            keep = install / "keep-user-data.txt"
            if keep.exists():
                keep.unlink()
            if install.exists():
                install.rmdir()
            for path in (cache, user_data):
                if path.exists():
                    shutil.rmtree(path)
            for extension in EXTENSIONS:
                key = "Software\\Classes\\" + extension
                if exists(key + r"\OpenWithProgids"):
                    winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, key + r"\OpenWithProgids")
                if exists(key):
                    winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, key)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\" + APP_ID, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "ScopeSentinel")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, "Software\\" + APP_ID)


if __name__ == "__main__":
    main()
