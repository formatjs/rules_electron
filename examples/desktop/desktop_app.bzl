"""Shared inputs for the two-version installation smoke."""

load("@rules_electron//electron:defs.bzl", "electron_app")

def desktop_app(name, package_json, **kwargs):
    """Assemble the generic sample with the requested app manifest."""
    electron_app(
        name = name,
        srcs = {
            "main.cjs": "main.cjs",
            "preload.cjs": "preload.cjs",
            ":renderer_bundle": "renderer",
            "assets/message.json": "assets/message.json",
            "native-package/index.cjs": "node_modules/example-native/index.cjs",
            "native-package/package.json": "node_modules/example-native/package.json",
            ":native_addon": "node_modules/example-native/addon.node",
            "@updater_npm//:runtime": "node_modules",
            "updater-smoke.cjs": "updater-smoke.cjs",
            "installed-update-smoke.cjs": "installed-update-smoke.cjs",
        },
        app_id = "org.example.sample-desktop",
        asar = True,
        asar_unpacked = ["node_modules/example-native/addon.node"],
        executable_name = "sample-desktop",
        extra_resources = select({
            ":windows": {
                ":helper": "native/helper.exe",
                ":update_config": "app-update.yml",
                ":update_smoke_feed": "update-smoke-feed",
                "resources/settings.json": "config/settings.json",
            },
            "//conditions:default": {
                ":helper": "native/helper",
                ":update_config": "app-update.yml",
                ":update_smoke_feed": "update-smoke-feed",
                "resources/settings.json": "config/settings.json",
            },
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
        macos_signer = select({
            ":macos": "@rcodesign_linux_x64//:rcodesign",
            "//conditions:default": None,
        }),
        package_json = package_json,
        product_name = "Sample Desktop",
        remove_package_scripts = True,
        runtime = ":runtime",
        **kwargs
    )
