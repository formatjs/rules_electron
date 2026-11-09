"""BB-only signing with explicitly public test identities; never release keys."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from electron.private.mac_sign import archive_bundle, signing_arguments
from electron.tools.notarize_macos import extract


if __name__ == "__main__":
    source, key, certificate, signer, entitlements, output = map(Path, sys.argv[1:])
    original = hashlib.sha256(source.read_bytes()).digest()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        configuration = root / "empty.toml"
        configuration.write_text("")
        environment = {"PATH": "", "HOME": str(root), "TMPDIR": str(root), "LC_ALL": "C.UTF-8", "TZ": "UTC"}
        outputs = []
        for index in range(2):
            stage = root / str(index)
            stage.mkdir()
            bundle = extract(source, stage)
            settings = signing_arguments(bundle, entitlements, entitlements, True)
            subprocess.run([str(signer), "sign", "--config-file", str(configuration), "--timestamp-url", "none",
                            "--signing-time", "2026-01-01T00:00:00Z", "--pem-file", str(certificate), "--pem-file", str(key),
                            *settings, str(bundle), str(bundle)], env=environment, check=True, capture_output=True, timeout=300)
            archive = stage / "signed.zip"
            archive_bundle(bundle, archive, bundle.name)
            outputs.append(archive)
        if hashlib.sha256(outputs[0].read_bytes()).digest() != hashlib.sha256(outputs[1].read_bytes()).digest():
            raise ValueError("Public macOS fixture signature is not reproducible")
        if hashlib.sha256(source.read_bytes()).digest() != original:
            raise ValueError("Public signing fixture changed its input")
        Path(output).write_bytes(outputs[0].read_bytes())
        Path(output).chmod(0o644)
        os.utime(output, (0, 0))
