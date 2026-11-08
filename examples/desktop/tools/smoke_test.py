"""Run the relocated packaged app with a real display and Chromium sandbox."""

import json
import argparse
import os
import platform
import hashlib
import plistlib
import re
from contextlib import contextmanager, nullcontext
from pathlib import Path
import select
import shutil
import subprocess
import struct
import sys
import tempfile
import time
import uuid


@contextmanager
def relocation_directory():
    directory = tempfile.TemporaryDirectory()
    try:
        yield directory.name
    finally:
        for attempt in range(50):
            try:
                directory.cleanup()
                break
            except PermissionError as error:
                # Chromium children can release Windows image mappings after app exit.
                if getattr(error, "winerror", None) not in (32, 33) or attempt == 49:
                    raise
                time.sleep(0.1)


@contextmanager
def display_server():
    read_fd, write_fd = os.pipe()
    with tempfile.TemporaryFile() as log:
        server = subprocess.Popen([
            "Xvfb", "-displayfd", str(write_fd), "-nolisten", "tcp",
            "-screen", "0", "1280x800x24",
        ], pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=log)
        os.close(write_fd)
        try:
            if not select.select([read_fd], [], [], 10)[0]:
                raise RuntimeError("Xvfb startup timed out")
            number = os.read(read_fd, 32).strip()
            if not number:
                log.seek(0)
                raise RuntimeError("Xvfb failed: " + log.read().decode())
            yield ":" + str(int(number))
        finally:
            os.close(read_fd)
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def check_windows_icon(executable, gray=43):
    import ctypes
    from ctypes import wintypes

    def bind(library, name, result, *arguments):
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments
        return function

    class IconInfo(ctypes.Structure):
        _fields_ = [("icon", wintypes.BOOL), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                    ("mask", wintypes.HANDLE), ("color", wintypes.HANDLE)]

    class BitmapHeader(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
                    ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                    ("image_size", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("used", wintypes.DWORD), ("important", wintypes.DWORD)]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [("header", BitmapHeader), ("colors", wintypes.DWORD * 256)]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    extract = bind(shell, "ExtractIconExW", wintypes.UINT, wintypes.LPCWSTR, ctypes.c_int,
                   ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), wintypes.UINT)
    info = IconInfo()
    icon = wintypes.HANDLE()
    assert extract(str(executable), 0, ctypes.byref(icon), None, 1) == 1
    dc = None
    try:
        if not bind(user, "GetIconInfo", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(IconInfo))(icon, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        assert info.color, "Executable icon has no color bitmap"
        dc = bind(gdi, "CreateCompatibleDC", wintypes.HANDLE, wintypes.HANDLE)(None)
        if not dc:
            raise ctypes.WinError(ctypes.get_last_error())
        get_bits = bind(gdi, "GetDIBits", ctypes.c_int, wintypes.HANDLE, wintypes.HANDLE, wintypes.UINT,
                        wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(BitmapInfo), wintypes.UINT)
        bitmap = BitmapInfo(header=BitmapHeader(size=ctypes.sizeof(BitmapHeader)))
        header = bitmap.header
        if not get_bits(dc, info.color, 0, 0, None, ctypes.byref(bitmap), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        width, height = header.width, abs(header.height)
        assert 0 < width <= 256 and 0 < height <= 256
        header.height, header.bits, header.compression = -height, 32, 0
        header.image_size, header.used = width * height * 4, 0
        pixels = ctypes.create_string_buffer(width * height * 4)
        assert get_bits(dc, info.color, 0, height, pixels, ctypes.byref(bitmap), 0) == height
        offset = (height // 2 * width + width // 2) * 4
        assert list(pixels.raw[offset:offset + 3]) == [gray, gray, gray]
    finally:
        if dc:
            bind(gdi, "DeleteDC", wintypes.BOOL, wintypes.HANDLE)(dc)
        for bitmap in [info.mask, info.color]:
            if bitmap:
                bind(gdi, "DeleteObject", wintypes.BOOL, wintypes.HANDLE)(bitmap)
        bind(user, "DestroyIcon", wintypes.BOOL, wintypes.HANDLE)(icon)
    print("EXAMPLE_ICON_SMOKE_OK")


def windows_resources(executable, expected_version):
    import ctypes
    from ctypes import wintypes

    def bind(library, name, result, *arguments):
        function = getattr(library, name)
        function.restype = result
        function.argtypes = arguments
        return function

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    load = bind(kernel, "LoadLibraryExW", wintypes.HMODULE, wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD)
    find = bind(kernel, "FindResourceW", wintypes.HANDLE, wintypes.HMODULE, wintypes.LPCWSTR, wintypes.LPCWSTR)
    size = bind(kernel, "SizeofResource", wintypes.DWORD, wintypes.HMODULE, wintypes.HANDLE)
    load_resource = bind(kernel, "LoadResource", wintypes.HGLOBAL, wintypes.HMODULE, wintypes.HANDLE)
    lock = bind(kernel, "LockResource", ctypes.c_void_p, wintypes.HGLOBAL)
    free = bind(kernel, "FreeLibrary", wintypes.BOOL, wintypes.HMODULE)
    module = load(str(executable), None, 0x22)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        resource = find(module, "ELECTRONASAR", "INTEGRITY")
        if not resource:
            raise ctypes.WinError(ctypes.get_last_error())
        address = lock(load_resource(module, resource))
        length = size(module, resource)
        if not address or not length:
            raise ctypes.WinError(ctypes.get_last_error())
        integrity = json.loads(ctypes.string_at(address, length))
    finally:
        free(module)

    version = ctypes.WinDLL("version", use_last_error=True)
    length = bind(version, "GetFileVersionInfoSizeW", wintypes.DWORD, wintypes.LPCWSTR, ctypes.c_void_p)(str(executable), None)
    if not length:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(length)
    get = bind(version, "GetFileVersionInfoW", wintypes.BOOL, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p)
    if not get(str(executable), 0, length, buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    query = bind(version, "VerQueryValueW", wintypes.BOOL, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT))
    address, length = ctypes.c_void_p(), wintypes.UINT()
    if not query(buffer, r"\VarFileInfo\Translation", ctypes.byref(address), ctypes.byref(length)) or length.value != 4:
        raise RuntimeError("Expected one Windows version translation")
    language, codepage = struct.unpack("<HH", ctypes.string_at(address, 4))
    if not query(buffer, "\\", ctypes.byref(address), ctypes.byref(length)) or length.value != 52:
        raise RuntimeError("Expected Windows fixed version information")
    fixed = struct.unpack("<13I", ctypes.string_at(address, 52))
    major, minor, patch = [int(part) for part in expected_version.split(".")]
    assert fixed[0] == 0xFEEF04BD
    assert fixed[2:6] == (major << 16 | minor, patch << 16 | 7,
                           major << 16 | minor, patch << 16)
    for key, expected in {
        "CompanyName": "Example", "ProductName": "Sample Desktop",
        "FileDescription": "Sample Desktop", "FileVersion": expected_version + ".7",
        "ProductVersion": expected_version, "InternalName": "sample-desktop",
        "OriginalFilename": "sample-desktop.exe",
    }.items():
        if not query(buffer, f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}", ctypes.byref(address), ctypes.byref(length)):
            raise RuntimeError("Missing Windows version string: " + key)
        assert ctypes.wstring_at(address, length.value - 1) == expected, key
    return integrity


def check_macos_icon(app):
    import ctypes
    from ctypes import c_void_p, c_char_p, c_long, c_double

    ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.argtypes, objc.objc_getClass.restype = [c_char_p], c_void_p
    objc.sel_registerName.argtypes, objc.sel_registerName.restype = [c_char_p], c_void_p

    def send(receiver, selector, result=c_void_p, *arguments):
        function = ctypes.CFUNCTYPE(result, c_void_p, c_void_p, *[kind for kind, _ in arguments])(("objc_msgSend", objc))
        return function(receiver, objc.sel_registerName(selector.encode()), *[value for _, value in arguments])

    def class_named(name):
        return objc.objc_getClass(name.encode())

    pool = send(class_named("NSAutoreleasePool"), "new")
    try:
        filename = send(class_named("NSString"), "stringWithUTF8String:", c_void_p, (c_char_p, os.fsencode(app)))
        workspace = send(class_named("NSWorkspace"), "sharedWorkspace")
        image = send(workspace, "iconForFile:", c_void_p, (c_void_p, filename))
        data = send(image, "TIFFRepresentation")
        bitmap = send(class_named("NSBitmapImageRep"), "imageRepWithData:", c_void_p, (c_void_p, data))
        assert bitmap, "Bundle icon has no bitmap representation"
        width, height = send(bitmap, "pixelsWide", c_long), send(bitmap, "pixelsHigh", c_long)
        assert width > 0 and height > 0
        color = send(bitmap, "colorAtX:y:", c_void_p, (c_long, width // 2), (c_long, height // 2))
        assert color, "Bundle icon has no RGB color"
        # Compare stored components; color conversion changes encoded gray.
        pixel = [round(send(color, component, c_double) * 255) for component in
                 ["redComponent", "greenComponent", "blueComponent", "alphaComponent"]]
        assert pixel == [43, 43, 43, 255], pixel
    finally:
        send(pool, "drain", None)
    print("EXAMPLE_ICON_SMOKE_OK")


def check_macos_protocol(app, environment, directory, target_arch):
    applications = Path.home() / "Applications"
    applications.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rules-electron-smoke-", dir=applications) as installed:
        bundle = Path(installed) / app.name
        subprocess.run(["/usr/bin/ditto", str(app), str(bundle)], check=True, timeout=30)
        _check_macos_protocol(bundle, environment, directory, target_arch)


def _check_macos_protocol(app, environment, directory, target_arch):
    executable = app / "Contents/MacOS/sample-desktop"
    metadata = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert metadata["CFBundleURLTypes"] == [{
        "CFBundleURLName": "Sample Desktop", "CFBundleURLSchemes": ["sample-desktop"],
        "CFBundleTypeRole": "Editor",
    }]
    register = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    report = directory / "protocol-result.json"
    url = "sample-desktop://smoke/" + uuid.uuid4().hex
    subprocess.run([register, "-f", str(app)], check=True, capture_output=True, timeout=15)
    try:
        check_macos_icon(app)
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([
                str(executable), "--protocol-smoke", str(report), "--disable-gpu",
                "--user-data-dir=" + str(directory / "protocol-profile"),
            ], env=environment, cwd=directory, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 15
                while not Path(str(report) + ".ready").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("macOS protocol receiver did not become ready")
                    time.sleep(0.1)
                delivery = subprocess.run(["/usr/bin/open", url], capture_output=True, text=True, timeout=15)
                if delivery.returncode:
                    details = {
                        "exit_code": delivery.returncode,
                        "osstatus": re.findall(r"Code=(-?\d+)", delivery.stderr),
                        "no_handler": "No application knows how to open" in delivery.stderr,
                        "permission_denied": "permission" in delivery.stderr.lower(),
                    }
                    raise RuntimeError("macOS protocol dispatch failed: " + json.dumps(details))
                if process.wait(timeout=25):
                    raise RuntimeError("macOS protocol receiver failed")
                assert json.loads(report.read_text()) == {
                    "url": url, "platform": "darwin", "architecture": target_arch,
                }
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    finally:
        subprocess.run([register, "-u", str(app)], check=True, capture_output=True, timeout=15)
    print("EXAMPLE_PROTOCOL_SMOKE_OK")


def check_asar_integrity(app, executable, environment, directory, target_os, expected_version):
    resources = app / ("Contents/Resources" if target_os == "macos" else "resources")
    digests, checks = {}, []
    for relative, entry_name, marker, skip, prefix in [
        ("app.asar", "package.json", b'"version":"', len(b'"version":"'), ""),
        ("plugins/shared.asar", "index.cjs", b"shared-asar-ready", 0, "additional_"),
    ]:
        archive = resources / relative
        with archive.open("rb") as source:
            framing = source.read(16)
            header_size = struct.unpack_from("<I", framing, 4)[0]
            raw_header = source.read(struct.unpack_from("<I", framing, 12)[0])
            entry = json.loads(raw_header)["files"][entry_name]
            payload_offset = 8 + header_size + int(entry["offset"])
            source.seek(payload_offset)
            payload = source.read(entry["size"])
        digests[relative] = hashlib.sha256(raw_header).hexdigest()
        checks += [
            (prefix + "header", archive, 16 + raw_header.index(entry["integrity"]["hash"].encode()),
             "Integrity check failed for asar archive"),
            (prefix + "payload", archive, payload_offset + payload.index(marker) + skip,
             "ASAR Integrity Violation: got a hash mismatch"),
        ]
    if target_os == "macos":
        metadata = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        assert metadata["CFBundleShortVersionString"] == expected_version
        assert metadata["CFBundleVersion"] == expected_version + ".7"
        for helper in (app / "Contents/Frameworks").glob("Sample Desktop Helper*.app"):
            identity = plistlib.loads((helper / "Contents/Info.plist").read_bytes())
            assert identity["CFBundleShortVersionString"] == expected_version
            assert identity["CFBundleVersion"] == expected_version + ".7"
        assert metadata["ElectronAsarIntegrity"] == {
            "Resources/" + relative: {"algorithm": "SHA256", "hash": digest} for relative, digest in digests.items()
        }
    else:
        assert windows_resources(executable, expected_version) == [
            {"file": "resources\\" + relative.replace("/", "\\"), "alg": "SHA256", "value": digests[relative]}
            for relative in sorted(digests)
        ]
    for label, archive, offset, diagnostic in checks:
        with archive.open("r+b") as file:
            file.seek(offset)
            original = file.read(1)
            file.seek(offset)
            file.write(b"0" if original != b"0" else b"1")
        try:
            result = subprocess.run([
                str(executable), "--smoke", "--disable-gpu", "--disable-dev-shm-usage",
                "--user-data-dir=" + str(directory / "profile"),
            ], cwd=directory, env=environment, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
            assert result.returncode != 0, label
            assert diagnostic in result.stderr, result.stdout + result.stderr
            assert "EXAMPLE_SMOKE_OK" not in result.stdout, result.stdout
            print("EXAMPLE_ASAR_REJECTED " + label)
        finally:
            with archive.open("r+b") as file:
                file.seek(offset)
                file.write(original)
    if target_os == "macos":
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--target-os", choices=["linux", "macos", "windows"], required=True)
    parser.add_argument("--target-arch", choices=["x64", "arm64"], required=True)
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--expected-version")
    parser.add_argument("--shortcut", action="append", default=[])
    parser.add_argument("--icon-only", action="store_true")
    parser.add_argument("--icon-gray", type=int, default=43)
    args = parser.parse_args()
    host_os = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
    host_arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if (host_os, host_arch) != (args.target_os, args.target_arch):
        raise RuntimeError(f"Smoke requires native {args.target_os}/{args.target_arch}; host is {host_os}/{host_arch}")
    if args.icon_only:
        if host_os != "windows":
            raise RuntimeError("Executable icon smoke requires Windows")
        if not 0 <= args.icon_gray <= 255:
            raise ValueError("Expected icon gray must fit 0..255")
        check_windows_icon(Path(args.app), args.icon_gray)
        raise SystemExit(0)
    if host_os == "windows":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x8003)
    if host_os == "linux":
        if not shutil.which("Xvfb"):
            raise RuntimeError("Install Xvfb for the Electron smoke test")
        subprocess.run(["unshare", "--user", "--map-root-user", "true"], check=True)
    source = Path(args.app).resolve()
    with relocation_directory() as directory:
        directory = Path(directory)
        app = directory / "relocated desktop app"
        if args.installed:
            if host_os not in ("linux", "windows"):
                raise ValueError("Installed-path smoke supports Linux/Windows")
            executable = source
            if host_os == "windows":
                app = source.parent
        elif host_os == "macos":
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(source), str(app)], check=True)
            bundles = list(app.glob("*.app"))
            if len(bundles) != 1:
                raise RuntimeError("Expected one packaged .app")
            app = bundles[0]
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            executable = app / "Contents/MacOS/sample-desktop"
        else:
            shutil.copytree(source, app)
            executable = app / ("sample-desktop.exe" if host_os == "windows" else "sample-desktop")
        environment = dict(os.environ)
        environment.update({
            "HOME": str(directory),
            "XDG_CONFIG_HOME": str(directory / "config"),
            "XDG_CACHE_HOME": str(directory / "cache"),
        })
        if not args.installed or host_os != "windows":
            environment.update(APPDATA=str(directory / "appdata"), LOCALAPPDATA=str(directory / "localappdata"))
        for name in ["ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"]:
            environment.pop(name, None)
        environment.update(ELECTRON_RUN_AS_NODE="1", NODE_OPTIONS="--not-a-valid-node-option")
        with (display_server() if host_os == "linux" else nullcontext()) as display:
            if display:
                environment["DISPLAY"] = display
            result = subprocess.run([
                str(executable), "--smoke", "--disable-gpu", "--disable-dev-shm-usage",
                "--user-data-dir=" + str(directory / "profile"),
                *[value for shortcut in args.shortcut for value in ["--shortcut-smoke", shortcut]],
            ], cwd=directory, env=environment, capture_output=True, encoding="utf-8", errors="replace", timeout=45)
        if result.returncode:
            raise RuntimeError(f"Electron exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
        if host_os == "windows":
            check_windows_icon(executable)
        lines = [line for line in result.stdout.splitlines() if line.startswith("EXAMPLE_SMOKE_OK ")]
        assert len(lines) == 1, result.stdout + result.stderr
        report = json.loads(lines[0].removeprefix("EXAMPLE_SMOKE_OK "))
        assert report["architecture"] == args.target_arch, report
        assert report["update_version"] == "2.0.0", report
        if args.expected_version:
            assert report["app_version"] == args.expected_version, report
        assert report["platform"] == {"linux": "linux", "macos": "darwin", "windows": "win32"}[args.target_os], report
        print("EXAMPLE_SMOKE_OK " + json.dumps(report, ensure_ascii=True))
        if host_os == "macos":
            check_macos_protocol(app, environment, directory, args.target_arch)
        if host_os in ("macos", "windows"):
            check_asar_integrity(app, executable, environment, directory, host_os, report["app_version"])
