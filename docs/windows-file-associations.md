# Windows file handlers

`electron_nsis.file_associations` maps lowercase extensions to descriptions:

```starlark
electron_nsis(
    name = "installer",
    app = ":app",
    tool = ":nsis_tool",
    file_associations = {".sample": "Sample Document"},
)
```

Each extension gets a stable app-specific ProgID, document description,
executable icon and quoted open command (`"app.exe" "%1"`). Registration uses
HKCU `Software\Classes`, `OpenWithProgids`, application `Capabilities` and
`RegisteredApplications`. The installer notifies the Windows shell after changes.
These handlers appear as Open With/Default Apps choices. Existing extension
defaults and protected `UserChoice` keys remain intact; users select defaults
through Windows. See [Microsoft's Default Programs contract](https://learn.microsoft.com/en-us/windows/win32/shell/default-programs).

ProgID and application registration conflicts stop installation before copying
the payload. Uninstall removes a handler only when its owner and open command
still match this installation. Other Open With entries and extension metadata
remain. The app handles opened paths through its Electron startup/second-instance
logic; packaging does not inject runtime handlers.

Extensions include the leading dot, then 1–32 lowercase letters/digits,
underscores or hyphens. Compound extensions, custom document icons, MIME types
and extra verbs are not yet supported.

The native Windows fixture checks shell command resolution, installed icons,
foreign registration rejection, update stability and uninstall cleanup while
preserving another app's extension default/Open With entry. Hosted validation
for these checks is pending. All packaging runs on BB Linux; Windows hosts only
install and exercise the resulting artifacts.
