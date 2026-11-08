"""Ad hoc bundle signing on the execution platform; no release credentials."""

import subprocess
import stat
import shutil
import plistlib
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from electron.private.runtime import normalize


def signing_arguments(source, entitlements="", entitlements_inherit="", hardened_runtime=False):
    source = Path(source)
    for filename in [entitlements, entitlements_inherit]:
        if filename and not isinstance(plistlib.loads(Path(filename).read_bytes(), fmt=plistlib.FMT_XML), dict):
            raise ValueError("Entitlements must be an XML plist dictionary")
    if not (entitlements or entitlements_inherit or hardened_runtime):
        return []
    info = plistlib.loads((source / "Contents/Info.plist").read_bytes())
    main = source / "Contents/MacOS" / info["CFBundleExecutable"]
    main = main.resolve().relative_to(source.resolve()).as_posix()
    arguments = []
    if entitlements:
        arguments += ["--entitlements-xml-file", "@main:" + str(Path(entitlements).resolve())]
    if hardened_runtime:
        arguments += ["--code-signature-flags", "@main:runtime"]
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            header = stream.read(32)
        magic = header[:4]
        if magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
            endian = "little" if magic[0] in (0xce, 0xcf) else "big"
            signable = len(header) >= 28 and int.from_bytes(header[12:16], endian) in (2, 6, 8, 9)
        elif magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca"):
            endian = "big" if magic[0] == 0xca else "little"
            signable = 0 < int.from_bytes(header[4:8], endian) <= 16
        else:
            signable = False
        if not signable:
            continue
        scope = path.relative_to(source).as_posix()
        settings = entitlements if scope == main else entitlements_inherit
        if settings:
            arguments += ["--entitlements-xml-file", scope + ":" + str(Path(settings).resolve())]
        if hardened_runtime:
            arguments += ["--code-signature-flags", scope + ":runtime"]
    return arguments


def sign_bundle(signer, source, output, entitlements="", entitlements_inherit="", hardened_runtime=False):
    arguments = signing_arguments(source, entitlements, entitlements_inherit, hardened_runtime)
    config = output.parent / "rcodesign.toml"
    config.write_text("")
    subprocess.run([signer, "sign", "--config-file", str(config), "--timestamp-url", "none", *arguments,
                    str(source), str(output)], check=True,
                   env={"LC_ALL": "C.UTF-8", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0", "HOME": str(config.parent)})
    # rcodesign 0.29 verify requires CMS; ad hoc signatures have none.
    # Native smoke checks the full bundle with Apple's codesign instead.
    normalize(output)


def archive_bundle(bundle, output, name):
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for path in sorted(bundle.rglob("*")):
            directory = path.is_dir() and not path.is_symlink()
            if directory and any(path.iterdir()):
                continue
            info = ZipInfo(name + "/" + path.relative_to(bundle).as_posix() + ("/" if directory else ""), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = path.lstat().st_mode
            info.external_attr = mode << 16
            if directory:
                archive.writestr(info, b"")
            elif stat.S_ISLNK(mode):
                archive.writestr(info, path.readlink().as_posix().encode())
            else:
                with path.open("rb") as source, archive.open(info, "w") as destination:
                    shutil.copyfileobj(source, destination)
