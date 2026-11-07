"""Electron v1 fuse wire, defined by electron/fuses src/{config,constants}.ts."""

import mmap

SENTINEL = b"dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX"
OPTIONS = {
    "runAsNode": 0,
    "enableCookieEncryption": 1,
    "enableNodeOptionsEnvironmentVariable": 2,
    "enableNodeCliInspectArguments": 3,
    "enableEmbeddedAsarIntegrityValidation": 4,
    "onlyLoadAppFromAsar": 5,
    "loadBrowserProcessSpecificV8Snapshot": 6,
    "grantFileProtocolExtraPrivileges": 7,
    "wasmTrapHandlers": 8,
}


def set_fuses(binary, settings):
    for name, state in settings.items():
        if name not in OPTIONS or state not in ("on", "off"):
            raise ValueError(f"Unsupported fuse setting: {name}={state}")
    with binary.open("r+b") as file, mmap.mmap(file.fileno(), 0) as data:
        sentinel = data.find(SENTINEL)
        if sentinel < 0 or data.find(SENTINEL, sentinel + 1) >= 0:
            raise ValueError("Expected one Electron fuse sentinel")
        start = sentinel + len(SENTINEL)
        if start + 2 > len(data) or data[start] != 1:
            raise ValueError("Expected Electron fuse wire version 1")
        count = data[start + 1]
        start += 2
        if start + count > len(data):
            raise ValueError("Truncated Electron fuse wire")
        writes = []
        for name, state in settings.items():
            index = OPTIONS[name]
            if index >= count or data[start + index] not in (0x30, 0x31):
                raise ValueError(f"Electron fuse unavailable: {name}")
            writes.append((start + index, 0x31 if state == "on" else 0x30))
        for position, value in writes:
            data[position] = value
