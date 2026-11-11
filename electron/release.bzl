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

def electron_macos_signing_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None, app = None, entitlements = None, entitlements_inherit = None):
    """Declare Developer ID signing without contacting Apple's notary service."""
    _macos_signing_client(name, signer, openssl, visibility, ["--sign-only"], Label("//electron/tools:sign_macos.py"), Label("//electron/tools:macos_release"), app, entitlements, entitlements_inherit)

def electron_macos_dmg_release_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None):
    """Declare Developer ID DMG signing followed by mandatory notarization/stapling."""
    _macos_signing_client(name, signer, openssl, visibility, [], Label("//electron/tools:release_dmg.py"), Label("//electron/tools:dmg_release"))

def electron_macos_dmg_signing_tool(name, signer, openssl = Label("@openssl//:openssl"), visibility = None):
    """Declare Developer ID DMG signing without notarization."""
    _macos_signing_client(name, signer, openssl, visibility, ["--sign-only"], Label("//electron/tools:release_dmg.py"), Label("//electron/tools:dmg_release"))

def _macos_signing_client(name, signer, openssl, visibility, arguments, source, library, app = None, entitlements = None, entitlements_inherit = None, data_extra = []):
    backend = name + "_backend"
    crypto = name + "_crypto"
    release_backend(name = backend, tool = signer)
    release_backend(name = crypto, tool = openssl)
    data = [":" + backend, ":" + crypto] + data_extra
    for flag, target in [("--input-runfile", app), ("--entitlements-runfile", entitlements), ("--entitlements-inherit-runfile", entitlements_inherit)]:
        if target:
            arguments = arguments + [flag, "$(rlocationpath %s)" % target]
            data.append(target)
    py_binary(
        name = name,
        srcs = [source],
        main = source,
        args = ["--backend", "$(rlocationpath :" + backend + ")", "--crypto", "$(rlocationpath :" + crypto + ")"] + arguments,
        data = depset([native.package_relative_label(target) for target in data]).to_list(),
        deps = [library],
        target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:x86_64"],
        visibility = visibility,
    )

def electron_macos_distribution_tool(name, app, signer, notarize = True, entitlements = None, entitlements_inherit = None, openssl = Label("@openssl//:openssl"), visibility = None):
    """Sign an app, build its DMG with declared tools, then sign and optionally notarize the image."""
    arguments = [] if notarize else ["--sign-only"]
    for suffix, tool in [("xorriso", Label("//electron/tools:xorriso")), ("converter", Label("//electron/tools:dmg"))]:
        release_backend(name = name + "_" + suffix, tool = tool)
        arguments += ["--" + suffix, "$(rlocationpath :" + name + "_" + suffix + ")"]
    _macos_signing_client(
        name,
        signer,
        openssl,
        visibility,
        arguments,
        Label("//electron/tools:distribute_macos.py"),
        Label("//electron/tools:macos_distribution"),
        app,
        entitlements,
        entitlements_inherit,
        [":" + name + "_xorriso", ":" + name + "_converter"],
    )
