# MSIX bundles

`electron_msix_bundle` combines x64/ARM64 application packages using native
Bazel actions and declared Python. It invokes no SDK packager or build wrapper.

```starlark
load("@rules_electron//electron:msix.bzl", "electron_msix_bundle")

electron_msix_bundle(
    name = "desktop",
    packages = [":x64_package", ":arm64_package"],
    package_names = {
        "x64": "Example-x64.msix",
        "arm64": "Example-arm64.msix",
    },
)
```

Configure input targets under their corresponding Bazel platforms. The rule also
accepts file groups; the example uses a split transition for both MSVC CPU
variants. Architecture comes from each package manifest, never the host.
Duplicate CPUs, filename collisions, mixed identities/versions and differing
manifests fail. Only `Identity.ProcessorArchitecture` may differ. Package bytes,
including existing signatures, stay unchanged.

`package_names` is optional; defaults are `package-x64.msix` and
`package-arm64.msix`. `bundle_version` defaults to the shared package version;
an override must contain four numeric components. No build clock enters output.
Inputs are application MSIX packages. Resource packages, optional/dependency
sets and flat bundles remain unsupported.

The embedded ZIP64 layout stores packages without outer compression. Its
[bundle manifest](https://learn.microsoft.com/en-us/uwp/schemas/bundlemanifestschema/element-package)
records exact data offsets/sizes and resource qualifiers. The bundle block map
hashes only `AppxMetadata/AppxBundleManifest.xml`, following
[Microsoft's reader](https://github.com/microsoft/msix-packaging/blob/master/src/msix/unpack/AppxPackageObject.cpp).
Each embedded package retains its own block map. XML ordering, ZIP metadata and
logical filenames are deterministic; temporary storage bounds memory use.

Output is unsigned. Sign the final bundle with the
[Windows release interface](signing.md), using its declared publisher identity.
Constructing the bundle does not establish package signature trust or Store
acceptance. App Installer `MainBundle` generation/publication remains separate
work; the existing descriptor rule currently handles `MainPackage` only.

Validation is pending. BB tests independently decode ZIP records, compare
payload bytes and offsets, verify the single-manifest block map, check input
relocation/order/mtime stability and reject incompatible inputs. The generic
example builds/signs v1/v2 bundles containing both CPUs. Native x64/ARM64 hosts
will verify trust, use `IAppxBundleReader`, check inner package identities and
offset bytes, install the matching payload, launch real bootstrap Electron,
upgrade and remove it. No foreign-CPU executable runs during these checks.
