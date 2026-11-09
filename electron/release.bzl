"""Uncached release clients with explicitly declared execution backends."""

load("@rules_python//python:defs.bzl", "py_binary")
load("//electron/private:release_backend.bzl", "release_backend")

def electron_macos_notarization_tool(name, signer, visibility = None):
    """Declare rcodesign's Linux notarization client; credentials enter at runtime."""
    _notarization_client(name, signer, visibility, Label("//electron/tools:notarize_macos.py"), Label("//electron/tools:notarization"))

def electron_macos_dmg_notarization_tool(name, signer, visibility = None):
    """Declare DMG notarization/stapling with immutable payload and signature checks."""
    _notarization_client(name, signer, visibility, Label("//electron/tools:notarize_dmg.py"), Label("//electron/tools:dmg_notarization"))

def _notarization_client(name, signer, visibility, source, library):
    backend = name + "_backend"
    release_backend(name = backend, tool = signer)
    py_binary(
        name = name,
        srcs = [source],
        main = source,
        args = ["--backend", "$(rlocationpath :" + backend + ")"],
        data = [":" + backend],
        deps = [library],
        target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:x86_64"],
        visibility = visibility,
    )

def electron_macos_release_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None):
    """Declare Developer ID signing followed by mandatory notarization/stapling."""
    _macos_signing_client(name, signer, openssl, visibility, [], Label("//electron/tools:sign_macos.py"), Label("//electron/tools:macos_release"))

def electron_macos_signing_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None):
    """Declare Developer ID signing without contacting Apple's notary service."""
    _macos_signing_client(name, signer, openssl, visibility, ["--sign-only"], Label("//electron/tools:sign_macos.py"), Label("//electron/tools:macos_release"))

def electron_macos_dmg_release_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None):
    """Declare Developer ID DMG signing followed by mandatory notarization/stapling."""
    _macos_signing_client(name, signer, openssl, visibility, [], Label("//electron/tools:release_dmg.py"), Label("//electron/tools:dmg_release"))

def electron_macos_dmg_signing_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None):
    """Declare Developer ID DMG signing without notarization."""
    _macos_signing_client(name, signer, openssl, visibility, ["--sign-only"], Label("//electron/tools:release_dmg.py"), Label("//electron/tools:dmg_release"))

def _macos_signing_client(name, signer, openssl, visibility, arguments, source, library):
    backend = name + "_backend"
    crypto = name + "_crypto"
    release_backend(name = backend, tool = signer)
    release_backend(name = crypto, tool = openssl)
    py_binary(
        name = name,
        srcs = [source],
        main = source,
        args = ["--backend", "$(rlocationpath :" + backend + ")", "--crypto", "$(rlocationpath :" + crypto + ")"] + arguments,
        data = [":" + backend, ":" + crypto],
        deps = [library],
        target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:x86_64"],
        visibility = visibility,
    )
