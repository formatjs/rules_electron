"""Bounded process-exit evidence for the real electron-updater installer launch."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import time

NAMES = {name.casefold(): name for name in ("sample-desktop.exe", "Sample-2.0.0.exe", "installer.exe", "Uninstall.exe")}


def events(path):
    if not path.exists():
        return []
    with path.open("rb") as source:
        data = source.read(65537)
    if len(data) > 65536:
        raise RuntimeError("NSIS process trace exceeds size limit")
    lines = data.splitlines()
    if not data.endswith(b"\n"):
        lines = lines[:-1]
    if len(lines) > 128:
        raise RuntimeError("NSIS process trace exceeds event limit")
    result = []
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeError):
            raise RuntimeError("Invalid NSIS process trace JSON") from None
        if not isinstance(entry, dict) or set(entry) != {"name", "stage", "exit_code"}:
            raise RuntimeError("Invalid NSIS process trace fields")
        name = NAMES.get(entry["name"].casefold()) if isinstance(entry["name"], str) else None
        code, stage = entry["exit_code"], entry["stage"]
        if not name or stage not in ("start", "stop") or (stage == "start" and code is not None) or (stage == "stop" and (type(code) is not int or not 0 <= code <= 0xffffffff)):
            raise RuntimeError("Invalid NSIS process trace values")
        result.append({"name": name, "stage": stage, "exit_code": code})
    return result


@contextmanager
def installer_trace(directory):
    output, ready = directory / "nsis-processes.ndjson", directory / "nsis-observer.ready"
    environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    observer = subprocess.Popen([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
        str(Path(__file__).with_name("windows_process_trace.ps1").resolve()), "-Output", str(output), "-Ready", str(ready),
    ], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while not ready.is_file():
            if observer.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("NSIS process observer did not become ready")
            time.sleep(0.1)

        def completed():
            seen = events(output)
            starts = [item for item in seen if item["name"] == "Sample-2.0.0.exe" and item["stage"] == "start"]
            stops = [item for item in seen if item["name"] == "Sample-2.0.0.exe" and item["stage"] == "stop"]
            if any(item["exit_code"] != 0 for item in stops):
                raise RuntimeError("NSIS installer process exited unsuccessfully")
            if starts and stops:
                return True
            if observer.poll() is not None:
                raise RuntimeError("NSIS process observer stopped before installer completion")
            return False

        yield completed
    finally:
        if observer.poll() is None:
            observer.terminate()
            try:
                observer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                observer.kill()
                observer.wait(timeout=5)
        try:
            report = {"ready": ready.is_file(), "events": events(output)}
        except RuntimeError:
            report = {"ready": ready.is_file(), "invalid_trace": True}
        resolved = Path(str(output) + ".resolved")
        if resolved.is_file():
            try:
                with resolved.open(encoding="ascii") as source:
                    value = source.read(16).strip()
            except (OSError, UnicodeError):
                value = ""
            if value.isascii() and value.isdigit() and 0 <= int(value) <= 128:
                report["resolved_starts"] = int(value)
            else:
                report["invalid_start_summary"] = True
        print("NSIS_PROCESS_TRACE " + json.dumps(report, sort_keys=True), flush=True)
