"""Shared inputs for the two-version installation smoke."""

load("@rules_electron//electron:defs.bzl", "electron_app")
load("@rules_electron//electron:metadata.bzl", "electron_package_json")
load("@rules_electron//electron:prepackaged.bzl", "electron_prepackaged_app")

def desktop_app(name, package_json, empty_resources = True, **kwargs):
    """Assemble the generic sample with the requested app manifest."""
    electron_package_json(
        name = name + "_package",
        src = package_json,
        dependency_manifests = [":native_package"],
        extra_metadata = "release-metadata.json",
        remove_fields = ["devDependencies"],
        remove_scripts = True,
    )
    electron_app(
        name = name + "_assembled",
        srcs = {
            "main.cjs": "main.cjs",
            "preload.cjs": "preload.cjs",
            ":renderer_files": "",
            "assets/message.json": "assets/message.json",
            ":workspace_npm": "node_modules",
            "@updater_npm//:runtime": "node_modules",
            "updater-smoke.cjs": "updater-smoke.cjs",
            "installed-update-smoke.cjs": "installed-update-smoke.cjs",
        },
        app_id = "org.example.sample-desktop",
        macos_extra_plist = select({
            ":macos": "document-types.plist",
            "//conditions:default": None,
        }),
        macos_protocols = select({
            ":macos": {"Sample Desktop": ["sample-desktop"]},
            "//conditions:default": {},
        }),
        build_number = "7",
        asar = True,
        asar_unpacked_patterns = ["**/*.node"],
        file_matcher = ":file_matcher",
        asar_symlinks = {
            "linked-main.cjs": "main.cjs",
            "linked-assets": "assets",
        },
        executable_name = "sample-desktop",
        extra_files = {"resources/NOTICE.txt": "licenses/NOTICE.txt"},
        extra_asars = {":shared_archive": "plugins/shared.asar"},
        resource_symlinks = select({
            ":macos": {"linked-config": "config", "nested/config": "linked-config"},
            "//conditions:default": {},
        }),
        extra_resources = select({
            ":windows": dict({
                ":example_document_icon": "document.ico",
                ":helper": "native/helper.exe",
                "@rules_electron//electron/tools:windows_elevate": "elevate.exe",
                ":update_config": "app-update.yml",
                ":update_smoke_feed": "update-smoke-feed",
                "resources/settings.json": "config/settings.json",
            }, **({":empty_resources": "directories"} if empty_resources else {})),
            "//conditions:default": dict({
                ":helper": "native/helper",
                ":update_config": "app-update.yml",
                ":update_smoke_feed": "update-smoke-feed",
                "resources/settings.json": "config/settings.json",
            }, **({":empty_resources": "directories"} if empty_resources else {})),
        }),
        fuses = select({
            ":macos": {
                "runAsNode": "off",
                "enableNodeOptionsEnvironmentVariable": "off",
                "enableNodeCliInspectArguments": "off",
                "enableEmbeddedAsarIntegrityValidation": "on",
                "onlyLoadAppFromAsar": "on",
                "grantFileProtocolExtraPrivileges": "off",
            },
            ":windows": {
                "runAsNode": "off",
                "enableNodeOptionsEnvironmentVariable": "off",
                "enableNodeCliInspectArguments": "off",
                "enableEmbeddedAsarIntegrityValidation": "on",
                "onlyLoadAppFromAsar": "on",
                "grantFileProtocolExtraPrivileges": "off",
            },
            "//conditions:default": {
                "runAsNode": "off",
                "enableNodeOptionsEnvironmentVariable": "off",
                "enableNodeCliInspectArguments": "off",
                "onlyLoadAppFromAsar": "on",
                "grantFileProtocolExtraPrivileges": "off",
            },
        }),
        windows_resource_tool = select({
            ":windows": ":windows_resource_tool",
            "//conditions:default": None,
        }),
        windows_metadata = select({
            ":windows": {"CompanyName": "Example"},
            "//conditions:default": {},
        }),
        windows_icon = select({
            ":windows": ":example_windows_icon",
            "//conditions:default": None,
        }),
        macos_signer = select({
            ":macos": "@rcodesign_linux_x64//:rcodesign",
            "//conditions:default": None,
        }),
        macos_entitlements = select({
            ":macos": "entitlements.plist",
            "//conditions:default": None,
        }),
        macos_entitlements_inherit = select({
            ":macos": "entitlements.plist",
            "//conditions:default": None,
        }),
        macos_hardened_runtime = select({
            ":macos": True,
            "//conditions:default": False,
        }),
        macos_icon = select({
            ":macos": ":example_icon",
            "//conditions:default": None,
        }),
        package_json = ":" + name + "_package",
        product_name = "Sample Desktop",
        remove_package_scripts = True,
        runtime = ":runtime",
        **kwargs
    )
    electron_prepackaged_app(
        name = name,
        src = ":" + name + "_assembled",
        package_json = ":" + name + "_package",
        executable_name = "sample-desktop",
        product_name = "Sample Desktop",
        app_id = "org.example.sample-desktop",
        build_number = "7",
        **kwargs
    )
