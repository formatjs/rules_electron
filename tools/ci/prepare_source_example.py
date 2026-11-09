"""Reuse the public desktop example with the pinned Linux source runtime."""

import argparse
import json
from pathlib import Path
import shutil


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Desktop source configuration changed; review source adaptation")
    return text.replace(before, after, 1)


def prepare_example(source, output, version):
    module = (source / "MODULE.bazel").read_text()
    module = replace_once(module, 'bazel_dep(name = "rules_rs", version = "0.0.86")',
                          'bazel_dep(name = "rules_rs", version = "0.2.1")')
    module += f'''
bazel_dep(name = "electron", version = "{version}")
bazel_dep(name = "rules_nodejs", version = "6.7.7")

node = use_extension("@rules_nodejs//nodejs:extensions.bzl", "node")
node.toolchain(node_version = "22.20.0")
use_repo(node, electron_nodejs_toolchains = "nodejs_toolchains")
register_toolchains("@electron_nodejs_toolchains//:all")

electron_rust = use_extension("@rules_rs//rs/toolchains:module_extension.bzl", "toolchains")
electron_rust.toolchain(edition = "2021", version = "nightly/2025-09-25")
use_repo(electron_rust, "default_rust_toolchains")
register_toolchains("@default_rust_toolchains//...")

rules_rust = use_extension("@rules_rs//rs:rules_rust.bzl", "rules_rust")
use_repo(rules_rust, "rules_rust")
'''
    build = (source / "BUILD.bazel").read_text()
    build = replace_once(build, '":linux_x64": "@bootstrap_electron_linux_x64//:runtime",',
                         '":linux_x64": ":source_runtime",')
    build = 'load("@rules_electron//tools/ci:source_runtime_archive.bzl", "source_runtime_archive")\n' + build
    build += '''
source_runtime_archive(
    name = "source_sdk_archive",
    srcs = ["@electron//source/distribution:electron-linux-x64.zip"],
    platform = "@electron//source/platforms:linux_amd64",
)

electron_runtime(
    name = "source_runtime",
    archive = ":source_sdk_archive",
    languages = ["en-US"],
    target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:x86_64"],
)
'''
    shutil.copytree(source, output, ignore=shutil.ignore_patterns(
        "bazel-*", "__pycache__", "*.pyc", ".bazelrc.user", "MODULE.bazel.lock"))
    (output / "MODULE.bazel").write_text(module)
    (output / "BUILD.bazel").write_text(build)
    with (output / ".bazelrc").open("a") as stream:
        stream.write('''
build --compilation_mode=opt
build --@rules_rust//rust/toolchain/channel=nightly
build:buildbuddy --config=bb-workflow
build:buildbuddy --platforms=@electron//source/platforms:linux_amd64
''')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pin = json.loads(Path(__file__).with_name("electron_source_pin.json").read_text())
    prepare_example(args.source, args.output, pin["version"])
    print("SOURCE_DESKTOP_EXAMPLE_PREPARED linux_x64=source other_variants=bootstrap")
