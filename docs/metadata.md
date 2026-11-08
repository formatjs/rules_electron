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
    extra_metadata = "release-metadata.json",
    remove_fields = ["devDependencies"],
    remove_scripts = True,
)
```

`extra_metadata` accepts a declared JSON object, including generated files.
Objects merge recursively; arrays, scalar values and null replace existing
values. Dependency maps can replace selected versions while retaining other
entries. `remove_fields` removes exact top-level names after merging; it does
not interpret dotted paths. `remove_scripts` then strips scripts. Explicit
`version` wins over the merged version; the final version must be valid SemVer.
Source manifests remain unchanged. Rewriting dependency metadata does not
install or prune package files: declare those through app inputs.

The desktop smoke checks merged dependency metadata, injected release fields
and removed development fields in the packaged ASAR.
[BB unit tests](https://formatjs.buildbuddy.io/invocation/798646af-1ae2-45d0-8be8-9c1e94a19f6f),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/8e276547-7b7a-4736-9efc-0dec5d6f3b9f)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42466409761)
passed, including both Windows compiler variants.

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
[48db5da packaging tests](https://formatjs.buildbuddy.io/invocation/7ef7befa-c521-45bb-97a2-080327eb40bd)
and [seven cross-build variants](https://formatjs.buildbuddy.io/invocation/9c7fc677-e132-4c44-84db-a5a125b92d9a)
passed. [Native smoke](https://github.com/formatjs/rules_electron/actions/runs/42438603219)
passed on Linux x64, macOS ARM64 and Windows x64/ARM64. It checks app/helper plist
build versions, PE version strings, DEB revision 7 and installed update flows.
Manifest tests verify override SemVer reaches both the assembled app and feed,
including prerelease/build metadata; invalid inputs fail before output.

[cdb98d6 validation](https://github.com/formatjs/rules_electron/actions/runs/42438901602)
also checks numeric PE FileVersion/ProductVersion words on both Windows CPUs
and compiler variants. All four matching native host jobs passed.
