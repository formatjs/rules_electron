"""Reproducible app archives from validated file and ZIP inventories."""

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import bz2
import gzip
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import stat
import sys
import tarfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

from electron.private.files import read_directories


@dataclass
class Entry:
    kind: str
    mode: int
    size: int = 0
    source: object = None
    target: str = ""


def relative(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or str(path) != name or ".." in path.parts or "\\" in name or ":" in name or "\0" in name:
        raise ValueError(f"Invalid archive path: {name!r}")
    return name


def validate(entries, platform):
    for name in list(entries):
        relative(name)
        for parent in PurePosixPath(name).parents:
            if str(parent) == ".":
                continue
            entries.setdefault(str(parent), Entry("directory", 0o755))
    if platform in ("windows", "macos") and len({name.casefold() for name in entries}) != len(entries):
        raise ValueError("Case-insensitive archive path collision")
    for name, entry in entries.items():
        if any(entries[str(p)].kind != "directory" for p in PurePosixPath(name).parents if str(p) != "."):
            raise ValueError(f"Archive file/directory collision: {name}")
        if entry.kind != "symlink":
            continue
        resolve(entries, name)


def resolve(entries, name):
    pending = list(PurePosixPath(relative(name)).parts)
    resolved, expansions = [], 0
    while pending:
        component = pending.pop(0)
        if component in ("", "."):
            continue
        if component == "..":
            if not resolved:
                raise ValueError(f"Escaping archive symlink: {name}")
            resolved.pop()
            continue
        node = entries.get("/".join(resolved + [component]))
        if node is None:
            raise ValueError(f"Dangling archive symlink: {name}")
        if node.kind == "symlink":
            expansions += 1
            if expansions > 40:
                raise ValueError(f"Cyclic archive symlink: {name}")
            target = node.target
            if not target or PurePosixPath(target).is_absolute() or any(c in target for c in ("\\", ":", "\0")):
                raise ValueError(f"Invalid archive symlink: {name}")
            pending = target.split("/") + pending
        else:
            if pending and node.kind != "directory":
                raise ValueError(f"Archive symlink traverses a file: {name}")
            resolved.append(component)
    return "/".join(resolved)


@contextmanager
def inventory(source, platform):
    entries = {}
    if source.is_dir():
        for directory, directories, files in os.walk(source, followlinks=False):
            for name in sorted(directories + files):
                path = Path(directory) / name
                mode = path.lstat().st_mode
                key = path.relative_to(source).as_posix()
                if stat.S_ISLNK(mode):
                    entries[key] = Entry("symlink", 0o777, target=os.readlink(path))
                elif stat.S_ISDIR(mode):
                    entries[key] = Entry("directory", 0o755)
                elif stat.S_ISREG(mode):
                    entries[key] = Entry("file", 0o755 if mode & 0o111 else 0o644, path.stat().st_size, path)
                else:
                    raise ValueError(f"Unsupported archive file type: {key}")
        validate(entries, platform)
        yield entries, lambda entry: entry.source.open("rb")
    else:
        if platform not in ("macos", "linux"):
            raise ValueError("Only Linux and macOS app inputs may be ZIPs")
        with ZipFile(source) as archive:
            stripped = [info.filename[:-1] if info.is_dir() else info.filename for info in archive.infolist()]
            for name in stripped:
                relative(name)
            root_names = {name.split("/", 1)[0] for name in stripped}
            linux_root = (next(iter(root_names)) if platform == "linux" and len(root_names) == 1 and
                          all("/" in name or info.is_dir() for name, info in zip(stripped, archive.infolist())) else None)
            roots = set()
            names = set()
            for info in archive.infolist():
                name = relative(info.filename[:-1] if info.is_dir() else info.filename)
                if name in names:
                    raise ValueError(f"Duplicate archive path: {name}")
                names.add(name)
                parts = name.split("/", 1)
                roots.add(parts[0])
                if platform == "macos" and not parts[0].endswith(".app"):
                    raise ValueError("Expected one macOS app bundle")
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                strip_root = platform == "macos" or linux_root is not None
                if strip_root and len(parts) == 1:
                    if not info.is_dir():
                        raise ValueError("App bundle root must be a directory")
                    continue
                key = parts[1] if strip_root else name
                if info.is_dir() and kind in (0, stat.S_IFDIR):
                    entries[key] = Entry("directory", 0o755)
                elif stat.S_ISLNK(mode):
                    if info.file_size > 65536:
                        raise ValueError("Archive symlink target too large")
                    entries[key] = Entry("symlink", 0o777, target=archive.read(info).decode("utf-8"))
                elif kind in (0, stat.S_IFREG) and not info.is_dir():
                    entries[key] = Entry("file", 0o755 if mode & 0o111 else 0o644, info.file_size, info)
                else:
                    raise ValueError(f"Unsupported archive file type: {name}")
            if platform == "macos" and len(roots) != 1:
                raise ValueError("Expected one macOS app bundle")
            validate(entries, platform)
            yield entries, lambda entry: archive.open(entry.source)


def sevenzip_archive(members, open_entry, tool, level, output):
    if not tool:
        raise ValueError("7z archives require a declared execution tool")
    tool, output = str(Path(tool).resolve()), str(Path(output).resolve())
    with tempfile.TemporaryDirectory(prefix="electron-7z-") as temporary:
        root = Path(temporary)
        for name, entry in members:
            destination = root / name
            if entry.kind == "symlink":
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if entry.kind == "directory":
                destination.mkdir(exist_ok=True)
            else:
                with open_entry(entry) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024**2)
            destination.chmod(entry.mode)
        for name, entry in members:
            if entry.kind == "symlink":
                (root / name).symlink_to(entry.target)
        for name, entry in reversed(members):
            os.utime(root / name, (315532800, 315532800), follow_symlinks=False)
        Path(output).unlink(missing_ok=True)
        subprocess.run([tool, "a", "-t7z", "-snl", "-mx=" + str(level),
                        "-m0=Copy" if not level else "-m0=LZMA2:d1m", "-mmt=2", "-ms=off",
                        "-mtc=off", "-mta=off", "-mtm=off", "-bd", "-bso0", "-bsp0",
                        output, "./" + members[0][0]], cwd=root,
                       env={"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0"}, check=True)


def write_tar(members, open_entry, stream):
    with tarfile.open(fileobj=stream, mode="w|", format=tarfile.PAX_FORMAT) as archive:
        for name, entry in members:
            info = tarfile.TarInfo(name)
            info.mode = entry.mode
            info.type = {"file": tarfile.REGTYPE, "directory": tarfile.DIRTYPE, "symlink": tarfile.SYMTYPE}[entry.kind]
            info.linkname = entry.target
            info.size = entry.size if entry.kind == "file" else 0
            if entry.kind == "file":
                with open_entry(entry) as content:
                    archive.addfile(info, content)
            else:
                archive.addfile(info)


def compressed_tar(members, open_entry, format, tool, level, output):
    if not tool:
        raise ValueError(format + " archives require a declared execution tool")
    tool, output = str(Path(tool).resolve()), Path(output).resolve()
    environment = {"PATH": "", "LC_ALL": "C.UTF-8", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0"}
    with tempfile.TemporaryDirectory(prefix="electron-tar-", dir=output.parent) as temporary:
        directory = Path(temporary)
        tar = directory / (members[0][0] + ".tar")
        with tar.open('wb') as destination:
            write_tar(members, open_entry, destination)
        tar.chmod(0o644)
        os.utime(tar, (0, 0))
        compressed = directory / ("release." + format)
        if format == 'tar.lz':
            with compressed.open('wb') as destination:
                subprocess.run([tool, '-c', '-' + str(level), './' + tar.name], cwd=directory,
                               env=environment, stdout=destination, check=True)
        else:
            subprocess.run([tool, 'a', '-t7z', '-mx=' + str(level),
                            '-m0=Copy' if not level else '-m0=LZMA2:d1m', '-mmt=2', '-ms=off',
                            '-mtc=off', '-mta=off', '-mtm=off', '-bd', '-bso0', '-bsp0',
                            str(compressed), './' + tar.name], cwd=directory, env=environment, check=True)
        os.replace(compressed, output)


def create_archive(source, platform, root_name, format, compression_level, output, directory_manifest="", sevenzip="", lzip=""):
    relative(root_name)
    if "/" in root_name or platform not in ("linux", "windows", "macos"):
        raise ValueError("Expected one archive root and a supported platform")
    if platform == "macos" and not root_name.endswith(".app"):
        raise ValueError("macOS archive root must end in .app")
    if format not in ("zip", "tar", "tar.gz", "tar.xz", "tar.bz2", "7z", "tar.lz", "tar.7z") or not 0 <= compression_level <= 9:
        raise ValueError("Invalid archive format or compression level")
    if format == "tar.bz2" and compression_level == 0:
        raise ValueError("tar.bz2 compression level must be between 1 and 9")
    with inventory(Path(source), platform) as (entries, open_entry):
        if directory_manifest:
            for path in read_directories(directory_manifest):
                path = str(path)
                if path in entries and entries[path].kind != "directory":
                    raise ValueError(f"Archive file/directory collision: {path}")
                entries[path] = Entry("directory", 0o755)
            validate(entries, platform)
        members = [(root_name, Entry("directory", 0o755))] + [(root_name + "/" + name, entry) for name, entry in sorted(entries.items())]
        if format == "7z":
            sevenzip_archive(members, open_entry, sevenzip, compression_level, output)
        elif format in ('tar.lz', 'tar.7z'):
            compressed_tar(members, open_entry, format, lzip if format == 'tar.lz' else sevenzip, compression_level, output)
        elif format == "zip":
            with ZipFile(output, "w") as archive:
                for name, entry in members:
                    info = ZipInfo(name + ("/" if entry.kind == "directory" else ""), (1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    mode = {"file": stat.S_IFREG, "directory": stat.S_IFDIR, "symlink": stat.S_IFLNK}[entry.kind] | entry.mode
                    info.external_attr = (mode << 16) | (0x10 if entry.kind == "directory" else 0)
                    info.compress_type = ZIP_DEFLATED if compression_level else ZIP_STORED
                    info._compresslevel = compression_level
                    if entry.kind == "file":
                        with open_entry(entry) as content, archive.open(info, "w", force_zip64=True) as destination:
                            shutil.copyfileobj(content, destination)
                    else:
                        archive.writestr(info, entry.target.encode("utf-8") if entry.kind == "symlink" else b"")
        else:
            with Path(output).open("wb") as raw:
                if format == "tar.gz":
                    stream = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=compression_level)
                elif format == "tar.xz":
                    stream = lzma.LZMAFile(raw, mode="w", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=compression_level)
                elif format == "tar.bz2":
                    stream = bz2.BZ2File(raw, mode="w", compresslevel=compression_level)
                else:
                    stream = nullcontext(raw)
                with stream as compressed:
                    write_tar(members, open_entry, compressed)


if __name__ == "__main__":
    create_archive(**json.loads(Path(sys.argv[1]).read_text()), output=sys.argv[2])
