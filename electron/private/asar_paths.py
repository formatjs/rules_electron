"""Validate and resolve the archive's virtual file/link namespace."""

from pathlib import PurePosixPath

from electron.private.files import relative_path


class ArchivePaths:
    def __init__(self, files, symlinks=None):
        self.files = set(files)
        self._declared = dict(symlinks or {})
        self.links = {}
        leaves = self.files | self._declared.keys()
        if self.files & self._declared.keys():
            raise ValueError("ASAR link/file collision")
        self._directories = {""}
        for name in sorted(leaves):
            path = relative_path(name)
            for parent in path.parents:
                parent = "" if parent == PurePosixPath(".") else str(parent)
                if parent in leaves:
                    raise ValueError(f"ASAR file/directory collision: {name}")
                self._directories.add(parent)
        for target in self._declared.values():
            if not isinstance(target, str):
                raise ValueError("ASAR link target must be a string")
            if target:
                relative_path(target)
        for name in sorted(self._declared):
            self._target(name, set())

    def _target(self, name, visiting):
        if name in visiting:
            raise ValueError(f"ASAR link cycle: {name}")
        if name not in self.links:
            self.links[name] = self._resolve(self._declared[name], visiting | {name})
        return self.links[name]

    def _resolve(self, path, visiting):
        while path:
            parts = path.split("/")
            for index in range(1, len(parts) + 1):
                prefix = "/".join(parts[:index])
                if prefix in self._declared:
                    target = self._target(prefix, visiting)
                    path = "/".join(([target] if target else []) + parts[index:])
                    break
            else:
                if path not in self.files and path not in self._directories:
                    raise ValueError(f"ASAR link target missing: {path}")
                return path
        return ""

    def resolve(self, path):
        relative_path(path)
        return self._resolve(path, set())
