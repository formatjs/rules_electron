"""Uncached release clients with explicitly declared execution backends."""

load("@rules_python//python:defs.bzl", "py_binary")
load("//electron/private:release_backend.bzl", "release_backend")

def electron_macos_notarization_tool(name, signer, visibility = None):
    """Declare rcodesign's Linux notarization client; credentials enter at runtime."""
    backend = name + "_backend"
    release_backend(name = backend, tool = signer)
    py_binary(
        name = name,
        srcs = [Label("//electron/tools:notarize_macos.py")],
        main = Label("//electron/tools:notarize_macos.py"),
        args = ["--backend", "$(rlocationpath :" + backend + ")"],
        data = [":" + backend],
        deps = [Label("//electron/tools:notarization")],
        target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:x86_64"],
        visibility = visibility,
    )
