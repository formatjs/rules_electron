# Linux DEB packages

`electron_deb` packages an assembled Linux app with deterministic metadata:

```starlark
load("@rules_electron//electron:linux.bzl", "electron_deb")

electron_deb(
    name = "deb",
    app = ":app",
    package_name = "example-desktop",
    maintainer = "Example Maintainers <maintainers@example.com>",
    description = "Example desktop app",
    depends = ["libgtk-3-0", "libnss3", "libasound2", "libgbm1"],
    protocols = ["example"],
    file_associations = {"application/x-example": ["*.example"]},
    file_association_icons = {"document.png": "application/x-example"},
    icons = {"icon.svg": "scalable"},
    setuid_sandbox = True,
)
```

The app must declare `app_id`. Files install beneath `/opt/<app_id>`, with a
launcher in `/usr/bin`, a desktop entry, optional MIME definitions and hicolor
icons. PNG icon mappings use pixel sizes such as `"256"`; SVG uses `"scalable"`.
`file_association_icons` maps declared PNG/SVG files to registered MIME types.
Square PNG headers select the hicolor pixel-size directory; SVG uses `scalable`.
Files install in `mimetypes/` using the
[standard MIME icon name](https://specifications.freedesktop.org/shared-mime-info/latest/ar01s02.html):
the MIME type with `/` replaced by `-`. Unknown MIME mappings, duplicate sizes,
non-square PNGs, malformed PNG headers/chunks and non-SVG roots fail packaging. [BB tests](https://formatjs.buildbuddy.io/invocation/fb94dbba-3278-42e5-bd81-82bbc4d7ee10),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/e5b19f38-f0ff-4c51-b0ff-bba60be49d74)
and [native Linux x64 smoke](https://github.com/formatjs/rules_electron/actions/runs/42539365870/job/128910750036)
passed for af0448f: icon lookup and PNG decoding after v1 installation and real
DebUpdater v2 installation, followed by purge.
GTK can choose a current theme's generic MIME icon before inherited hicolor
icons; see [theme lookup order](https://docs.gtk.org/gtk3/method.IconTheme.choose_icon.html).
The smoke checks named lookup through normal theme inheritance and GIO MIME
resolution in hicolor, then decodes the installed PNG. A user's selected theme
can override its presentation.
Desktop/MIME registration advertises handlers; choosing user defaults remains an
OS/user operation.

CPU constraints select Debian `amd64` or `arm64`. The app manifest supplies the
version; SemVer prereleases map to Debian `~` ordering. `revision` is separate
from the app version and defaults to `1`. Declare runtime dependencies for the
target distribution explicitly; packaging does not discover host libraries.

Default post-install/removal scripts refresh available desktop, MIME and icon
caches. Optional `preinst`, `postinst`, `prerm`, `postrm` labels replace those
stages with declared scripts. No maintainer script executes during builds.
The installed `resources/package-type` marker selects `DebUpdater` when the app
uses electron-updater's `autoUpdater` export.

The container is produced by pinned `rules_pkg`; payload generation uses the
pinned execution Python toolchain. File order, ownership, modes and timestamps
are fixed. Gzip headers omit source paths and clocks. Relative internal app
symlinks are preserved; absolute, dangling or escaping links fail. Packaging
never executes the target binary, invokes `dpkg`, or probes the execution host.

The example cross-builds v1/v2 DEBs for both Linux CPUs on BB. Its native Linux
x64 job installs v1, checks metadata and a sandboxed launch, rejects a corrupted
download, installs v2 through real `DebUpdater`, launches v2 and purges the
package. Headless CI supplies an elevation adapter backed by the runner's sudo;
the updater, downloader and dpkg installation remain real. No ARM64 installation
claim is made without a native smoke host.

`setuid_sandbox = True` installs the app-root `chrome-sandbox` helper as
root:root with mode `4755`. Packaging requires a separate regular executable
ELF64 helper matching the target CPU; missing helpers, symlinks, scripts and
wrong architectures fail. Input permissions remain unchanged. The default
retains normalized `0755` executable modes for user-namespace sandboxing.

Example DEBs enable this option. Installed v1/v2 smoke checks helper ownership
and mode, clears host sandbox overrides, and launches with
`--disable-namespace-sandbox` to exercise Chromium's setuid fallback. Both versions,
installed updater and purge passed on the native Linux x64 host for
[255731d](https://github.com/formatjs/rules_electron/actions/runs/42520835627/job/128853879770).
Distribution-specific confinement and AppImage remain open.

## RPM

`electron_rpm` emits unsigned RPM v4 packages for Linux `x86_64`/`aarch64`:

```starlark
load("@rules_electron//electron:linux.bzl", "electron_rpm")

electron_rpm(
    name = "rpm",
    app = ":app",
    package_name = "example-desktop",
    summary = "Example Desktop",
    description = "Example desktop app",
    license = "MIT",
    requires = ["gtk3", "nss", "alsa-lib", "mesa-libgbm"],
    file_associations = {"application/x-example": ["*.example"]},
    file_association_icons = {"document.png": "application/x-example"},
)
```

Payload layout, desktop/MIME/icons, internal links and optional setuid helper
follow the DEB contract. RPM owns private app directories and installed files;
shared OS directory ownership stays with distribution packages. `release` defaults to the app build number, then `1`.
RPM versions map SemVer prereleases to `~`; SemVer build metadata does not affect
RPM version ordering. App and updater versions retain the full manifest version.
`requires` accepts capability names and simple comparisons such as
`"glibc >= 2.31"`. No host dependency discovery or automatic ELF scanning runs.
Consumers supply complete dependencies for their target distribution.

The declared Python toolchain writes the
[RPM v4 container](https://rpm.org/docs/4.20.x/manual/format_v4.html), immutable
header regions, SHA-256 header/payload/file digests and a streamed CPIO/gzip
payload. Paths, ownership, modes, order and timestamps are fixed. No `rpmbuild`,
host macros, target execution, CMake or foreign_cc action participates. Individual
files and total installed payload must fit below 4 GiB. Signature metadata also
includes legacy format digests for compatibility; packages remain unsigned.
Release signing and trust policy remain separate work.

`prein`, `postin`, `preun`, `postun` take declared shell scripts. Defaults refresh
available desktop/MIME/icon caches after installation and removal. Scripts run
only under the destination package manager. The installed `package-type` marker
selects real `RpmUpdater`; generate its feed from the final RPM with
`electron_update_feed`.

[BB tests](https://formatjs.buildbuddy.io/invocation/276cf1f2-461e-4ee6-a306-c0b28eb38d92),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/d2da0d6a-fcdb-4484-a424-c062871ba902)
and [native Fedora lifecycle](https://github.com/formatjs/rules_electron/actions/runs/42544004368/job/128925130857)
passed with electron-updater 6.8.11 and its corrected dnf detection.
CI cross-builds both CPUs on BB. Native Linux x64
smoke provisions an immutable official Fedora 43 container, installs the BB
artifact through dnf, checks real RPM digests/file verification, launches v1,
rejects a corrupted update, installs v2 through `RpmUpdater`, launches v2 and
removes the package. The container executes natively; no ARM64 smoke claim is
made. OS provisioning installs test libraries; it performs no app compilation
or packaging. Container launches use `--no-sandbox`; RPM helper ownership/mode
are checked separately from the DEB setuid sandbox execution gate.
