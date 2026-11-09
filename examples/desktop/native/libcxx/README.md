# Electron 39 C++ runtime

The bootstrap addon SDK builds Chromium's matching libc++ sources with native
`cc_library` actions. No prebuilt libc++ objects, GN or CMake actions run.

Inputs come from Chromium 142.0.7444.52:

- [DEPS](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/DEPS)
  pins libc++ `b77132b512d5411f8393fd3decb3abaeaf1d3ec8`, mirrored from LLVM
  `1ab4113d0e0d30ba923ea070530a0e65910b26cb`.
- [libc++ BUILD.gn](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/buildtools/third_party/libc%2B%2B/BUILD.gn)
  supplies the source list and platform additions.
- `chromium-config.patch` adds Electron's released
  [__config_site](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/buildtools/third_party/libc%2B%2B/__config_site)
  and [__assertion_handler](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/buildtools/third_party/libc%2B%2B/__assertion_handler).
  Electron changes Chromium's ABI version to 1 and enables iterator wrappers
  for arrays/string views; namespace stays `std::__Cr`. Config bytes match
  Electron 39's `libcxx_headers.zip` (SHA-256
  `35a424a27fac622993c612b33daf7ab316cf250796eeb57f6d3eba5a311be248`).
  All 1,680 released headers match the pinned libc++ source bytes.
  These changes come from Electron's
  [original ABI patch](https://github.com/electron/electron/blob/v39.0.0/patches/chromium/build_make_libcxx_abi_unstable_false_for_electron.patch).
- [C++ runtime settings](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/build/config/c%2B%2B/BUILD.gn)
  supply visibility, sanitizer and Windows VCRuntime policy. Compiler, C runtime
  and exception ABI runtime remain declared hermetic LLVM toolchain inputs.
- [LLVM-libc shared headers](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/third_party/llvm-libc/BUILD.gn)
  supply floating-point parsing internals. All 141 declared headers match the
  pinned Chromium LLVM-libc revision `0c61a55402c6a0d9d6ca2aeb3c6a2613a8bc8c55`
  byte for byte. They share the stable LLVM archive above; `LIBC_NAMESPACE`
  stays private to libc++ compilation.

`sdk_cxxstdlib = True` selects the toolchain's hosted C-runtime stage. Linux
imports the toolchain's source-built libc++abi/libunwind archives explicitly;
macOS uses the declared SDK's libc++abi; Windows uses VCRuntime. The default
toolchain libc++ headers cannot enter this SDK's include search path.

The addon passes `std::shared_ptr<v8::BackingStore>` into Electron, gets it back,
checks shared ownership and returns the same bytes to JavaScript. Main-thread
and worker smoke both check the result. This exercises the STL boundary omitted
by the basic integer callback.

This SDK matches the explicit bootstrap runtime. A source-built runtime needs
headers and libc++ settings from its producer; its SDK remains separate work.
