# App and build identity

`electron_package_json` validates package SemVer and writes stable JSON. Its
`version` attribute overrides the source version; `remove_scripts` strips root
package scripts. Other metadata stays intact. Share its output between
`electron_app.package_json` and `electron_update_feed.package_json` so the app,
installers and update feed use the same release version.

```starlark
load("@rules_electron//electron:metadata.bzl", "electron_package_json")

electron_package_json(
    name = "release_package",
    src = "package.json",
    version = "2.3.4-beta.1+build.7",
    remove_scripts = True,
)
```

`electron_app` accepts explicit `build_number` and `build_version` attributes.
Package SemVer remains the application/update identity and Windows ProductVersion.
Build identity writes macOS CFBundleVersion on the app and helpers, Windows PE
FileVersion, and NSIS installer FileVersion/numeric version.

- `build_number = "7"` uses the numeric package version plus the iteration:
  `2.3.4.7`, including for prereleases.
- `build_version = "4.5.6.8"` sets native build metadata directly and takes
  precedence over `build_number` there.
- DEB revision defaults to `build_number`, then `1`. An explicit
  `electron_deb.revision` takes precedence.

Build numbers are canonical nonnegative decimal strings. Explicit build versions
contain one to four decimal components; Windows components must fit 0..65535.
Windows build metadata requires `windows_resource_tool`. All values are declared
inputs. CI environment variables and clocks supply no defaults.

The [electron-builder contract](https://www.electron.build/docs/api/app-builder-lib.interface.commonconfiguration/)
uses the same distinction between release version, build version and build number.
The generic desktop example sets build number 7 across its target variants;
matching native smoke hosts inspect PE/plist metadata and installed DEB revision.
Hosted validation is pending.
