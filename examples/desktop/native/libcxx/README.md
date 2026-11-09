# Electron 39 C++ runtime

The bootstrap addon SDK builds Chromium's matching libc++ sources with native
`cc_library` actions. No prebuilt libc++ objects, GN or CMake actions run.

Inputs come from Chromium 142.0.7444.52:

- [DEPS](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/DEPS)
  pins libc++ `b77132b512d5411f8393fd3decb3abaeaf1d3ec8`, mirrored from LLVM
  `1ab4113d0e0d30ba923ea070530a0e65910b26cb`.
- [libc++ BUILD.gn](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/buildtools/third_party/libc%2B%2B/BUILD.gn)
  supplies the source list and platform additions.
- `chromium-config.patch` adds the original
  [__config_site](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/buildtools/third_party/libc%2B%2B/__config_site)
  and [__assertion_handler](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/buildtools/third_party/libc%2B%2B/__assertion_handler).
  They select ABI version 2 and namespace `std::__Cr`.
- [C++ runtime settings](https://chromium.googlesource.com/chromium/src/+/142.0.7444.52/build/config/c%2B%2B/BUILD.gn)
  supply visibility, sanitizer and Windows VCRuntime policy. Compiler, C runtime
  and exception ABI runtime remain declared hermetic LLVM toolchain inputs.

The addon passes `std::shared_ptr<v8::BackingStore>` into Electron, gets it back,
checks shared ownership and returns the same bytes to JavaScript. Main-thread
and worker smoke both check the result. This exercises the STL boundary omitted
by the basic integer callback.

This SDK matches the explicit bootstrap runtime. A source-built runtime needs
headers and libc++ settings from its producer; its SDK remains separate work.
