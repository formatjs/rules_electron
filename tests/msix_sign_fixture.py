"""BB-only public-key signing fixture and deliberate bad-digest package."""

import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from zipfile import ZipFile


def run(arguments, environment):
    result = subprocess.run(arguments, env=environment, capture_output=True)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).decode(errors="replace")[-2000:])


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").digest()


if __name__ == "__main__":
    signer, source, key, certificate, config, output, tampered, payload_name = sys.argv[1:]
    environment = {"PATH": "", "LC_ALL": "C", "TZ": "UTC", "OPENSSL_CONF": config}
    command = [signer, "sign", "-certs", certificate, "-key", key, "-h", "sha256", "-time", "1767225600", "-in", source, "-out"]
    run(command + [output], environment)
    with tempfile.TemporaryDirectory() as temporary:
        repeated = str(Path(temporary) / "repeated.msix")
        run(command + [repeated], environment)
        if digest(output) != digest(repeated):
            raise ValueError("Public fixture MSIX signature is not reproducible")
    run([signer, "verify", "-CAfile", certificate, "-ignore-cdp", "-time", "1767225600", "-in", output], environment)
    if not tampered:
        raise SystemExit(0)
    with ZipFile(output) as package:
        payload = package.getinfo(payload_name)
    data = bytearray(Path(output).read_bytes())
    name_size, extra_size = struct.unpack_from("<HH", data, payload.header_offset + 26)
    offset = payload.header_offset + 30 + name_size + extra_size
    if payload.compress_size < 2:
        raise ValueError("Fixture PE payload unexpectedly empty")
    data[offset + payload.compress_size // 2] ^= 1
    Path(tampered).write_bytes(data)
