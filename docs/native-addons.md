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

Set `sdk_cxxstdlib = True` when the SDK supplies its own C++ headers and runtime.
This selects hermetic LLVM's hosted C-runtime stage, keeping declared target C
headers/CRTs while excluding its default C++ headers and automatic C++ linkage.
The SDK must supply its C++ library and exception ABI dependencies explicitly.
This prevents incompatible libc++ wrappers from mixing through `#include_next`.

Windows builds use the matching CPU's MSVC ABI and static CRT, including when the
app's other native helpers use GNU LLVM. These builds require licensed MSVC runtime
hosts and the existing license acknowledgment flag. The declared delay-load hook
resolves Electron exports from the current process after executable renaming. The SDK must
provide Electron's `node.lib`; linking delays `node.exe` resolution. Linux/macOS
resolve runtime exports at load time. See
[Electron's native module contract](https://www.electronjs.org/docs/latest/tutorial/using-native-node-modules).

Delay loading compiles the original public-domain MinGW-w64 14 implementation
with native Bazel C rules and declared MSVC SDK headers. Two public header aliases
bridge its MinGW type/anonymous-union spellings. No Visual Studio `delayimp.h` or
prebuilt `delayimp.lib` is assumed; hooks and the resolver ship in the addon.

The public desktop fixture keeps its stable Node-API addon and adds a context-aware
Node/V8 addon. Its explicit bootstrap SDK pins Electron 39 headers/import libraries
and V8's compression, sandbox and external-code-space settings. Native smoke calls
V8 functions in the main thread and a worker, checks ABI 140 and rejects a module
deliberately built for ABI 139. All seven payload variants check addon architecture.
All seven variants [cross-built on BB](https://formatjs.buildbuddy.io/invocation/dd78db17-584f-45c7-acc8-0341811df7ae).
Native Linux x64, macOS ARM64 and Windows x64/ARM64 pass main/worker calls and
wrong-ABI rejection in [the native run](https://github.com/formatjs/rules_electron/actions/runs/42647252981).

The bootstrap SDK now builds Chromium's exact libc++ sources with native Bazel
rules, Electron's ABI version 1/`std::__Cr` configuration and declared toolchain
runtime inputs. The new main/worker probes pass shared backing-store ownership
across V8's STL boundary and check the returned bytes. All seven variants
[cross-build on BB](https://formatjs.buildbuddy.io/invocation/aca4f1f5-ccaf-4d7e-bdb8-4fe543a52fa4).
Linux x64, macOS ARM64 and Windows x64/ARM64 pass these probes and the existing
installer/update checks in [the native run](https://github.com/formatjs/rules_electron/actions/runs/42661122523).
See the [source inputs](../examples/desktop/native/libcxx/README.md).
The source overlay now exposes `@electron//sdk:node_v8_addon_sdk`: patched
Node/libuv/V8 headers and captured public ABI settings, with zero Node/V8 link
inputs. Use the producer's LLVM C++ runtime, leaving `sdk_cxxstdlib` false.
The standalone Linux source runtime [passes](https://formatjs.buildbuddy.io/invocation/923e0e81-cb57-4eae-af83-26dbdbbcb0ee)
backing-store ownership/bytes in the main thread and a worker after relocation
and executable renaming, under both C/ASCII and C.UTF-8/Unicode paths.
The source desktop adapter selects this SDK for Linux x64; other triples keep
their explicit bootstrap SDK. The [1361 source desktop build](https://formatjs.buildbuddy.io/invocation/b6c026bb-e5be-469c-a797-1c190931e9df)
and [native smoke](https://github.com/formatjs/rules_electron/actions/runs/42790155958)
now pass Linux x64 desktop/package/updater launch with this SDK. Nine app reports
passed, including Node/V8 ABI 140 and the main/worker backing-store checks.
Source runtimes and SDKs for other triples remain open.
