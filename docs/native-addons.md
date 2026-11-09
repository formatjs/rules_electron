# Node/V8 addons

`electron_cc_addon` compiles declared C++ sources against an explicit Electron SDK:

```starlark
load("@rules_electron//electron:native.bzl", "electron_cc_addon")

electron_cc_addon(
    name = "addon",
    srcs = ["addon.cc"],
    headers = "@electron_sdk//:headers",
)
```

The SDK supplies `CcInfo`: matching Node/V8 headers, public ABI defines and Windows
import libraries. Extra compile/link options and dependencies remain explicit.
The SDK and C++ runtime must match Electron; ordinary Node headers are insufficient.
No host Node, npm lifecycle scripts, node-gyp or `binding.gyp` interpretation runs.
Package the resulting single artifact under a `.node` destination.

Windows builds use the matching CPU's MSVC ABI and static CRT, including when the
app's other native helpers use GNU LLVM. These builds require licensed MSVC runtime
hosts and the existing license acknowledgment flag. The declared delay-load hook
resolves Electron exports from the current process after executable renaming. The SDK must
provide Electron's `node.lib`; linking delays `node.exe` resolution. Linux/macOS
resolve runtime exports at load time. See
[Electron's native module contract](https://www.electronjs.org/docs/latest/tutorial/using-native-node-modules).

The public desktop fixture keeps its stable Node-API addon and adds a context-aware
Node/V8 addon. Its explicit bootstrap SDK pins Electron 39 headers/import libraries
and V8's compression, sandbox and external-code-space settings. Native smoke calls
V8 functions in the main thread and a worker, checks ABI 140 and rejects a module
deliberately built for ABI 139. All seven payload variants check addon architecture.
Hosted build/runtime validation for this new adapter is pending. Source-generated
SDK inputs and broader addon compiler/runtime combinations still need coverage.
