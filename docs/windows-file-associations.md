# Windows file handlers

`electron_nsis.file_associations` maps lowercase extensions to descriptions:

```starlark
electron_nsis(
    name = "installer",
    app = ":app",
    tool = ":nsis_tool",
    file_associations = {".sample": "Sample Document"},
    file_association_icons = {".sample": "resources/document.ico"},
    file_association_verbs = {".sample": ["edit", "print"]},
    file_association_verb_labels = {"edit": "Edit Sample Document"},
)
```

Each extension gets a stable app-specific ProgID, document description,
executable icon and quoted open command (`"app.exe" "%1"`). Registration uses
the selected scope's HKCU/HKLM `Software\Classes`, `OpenWithProgids`, application `Capabilities` and
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
underscores or hyphens. Declared document ICO files must already ship in the app.
Compound extensions and MIME types remain unsupported.

`file_association_verbs` adds app-owned shell actions such as `edit` and `print`.
Names use 1–32 lowercase letters/digits, underscores or hyphens, starting with a
letter; `open` is reserved. Commands pass `--file-association-verb=NAME` followed
by the quoted document path. The app handles that switch; packaging adds no
runtime handler. Optional labels are keyed by declared verb name. Open remains
the default action. Upgrades replace owned commands, removing retired verbs;
uninstall uses the existing ownership and open-command guards. See
[Microsoft's shell verb contract](https://learn.microsoft.com/en-us/windows/win32/shell/fa-verbs).

The expanded native fixture resolves each extra command through Windows shell
APIs, launches it with a Unicode/spaces document path, and checks the app receives
the verb and reads the document. User/machine upgrades also remove a seeded stale
verb. [BB tests](https://formatjs.buildbuddy.io/invocation/c09d00f6-8dc7-488d-b1c4-8bc696c09ef3)
and [all seven cross-builds](https://formatjs.buildbuddy.io/invocation/26b5756f-b9fe-4288-990f-efeeb38edbdb)
passed. Native [Windows x64](https://github.com/formatjs/rules_electron/actions/runs/42635829460/job/129223941911)
and [ARM64](https://github.com/formatjs/rules_electron/actions/runs/42635829460/job/129223942031)
passed all four user/machine, before/after-update verb checks per CPU, including
document execution and stale-command removal. Installer checks use MSVC packages;
both GNU LLVM and MSVC app variants also pass native launch.

The native Windows fixture checks shell command resolution, installed icons,
foreign registration rejection, update stability and uninstall cleanup while
preserving another app's extension default/Open With entry.
[BB unit tests](https://formatjs.buildbuddy.io/invocation/6a3e0c79-fe1a-4000-bfd5-e4c3e17c9b61),
[seven cross-builds](https://formatjs.buildbuddy.io/invocation/89538d73-818d-4d76-8dcd-897327668de0)
and [all four native hosts](https://github.com/formatjs/rules_electron/actions/runs/42467990963)
passed. Both Windows CPUs passed installed handler checks with MSVC packages.
All packaging runs on BB Linux; Windows hosts only install and exercise outputs.
