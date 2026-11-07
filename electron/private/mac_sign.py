"""Ad hoc bundle signing on the execution platform; no release credentials."""

import subprocess
import stat
import shutil
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from electron.private.runtime import normalize


def sign_bundle(signer, source, output):
    subprocess.run([signer, "sign", str(source), str(output)], check=True)
    subprocess.run([signer, "verify", str(output)], check=True)
    normalize(output)


def archive_bundle(bundle, output, name):
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            info = ZipInfo(name + "/" + path.relative_to(bundle).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = path.lstat().st_mode
            info.external_attr = mode << 16
            if stat.S_ISLNK(mode):
                archive.writestr(info, path.readlink().as_posix().encode())
            else:
                with path.open("rb") as source, archive.open(info, "w") as destination:
                    shutil.copyfileobj(source, destination)
