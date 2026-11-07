"""Native smoke transport groups; Linux ARM64 remains cross-build only."""

SHARDS = {
    "linux-x64": ("linux_x86_64",),
    "macos-arm64": ("macos_aarch64",),
    "windows-x64": ("windows_x86_64_gnullvm", "windows_x86_64_msvc"),
    "windows-arm64": ("windows_aarch64_gnullvm", "windows_aarch64_msvc"),
}

ALL_VARIANTS = frozenset(variant for variants in SHARDS.values() for variant in variants) | {"linux_aarch64"}


def archive_name(shard):
    if shard not in SHARDS:
        raise ValueError(f"Unsupported smoke shard: {shard}")
    return "electron-smoke-" + shard + ".zip"
