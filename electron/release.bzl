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

def electron_macos_release_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None):
    """Declare Developer ID signing followed by mandatory notarization/stapling."""
    backend = name + "_backend"
    crypto = name + "_crypto"
    release_backend(name = backend, tool = signer)
    release_backend(name = crypto, tool = openssl)
    py_binary(
        name = name,
        srcs = [Label("//electron/tools:sign_macos.py")],
        main = Label("//electron/tools:sign_macos.py"),
        args = ["--backend", "$(rlocationpath :" + backend + ")", "--crypto", "$(rlocationpath :" + crypto + ")"],
        data = [":" + backend, ":" + crypto],
        deps = [Label("//electron/tools:macos_release")],
        target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:x86_64"],
        visibility = visibility,
    )
