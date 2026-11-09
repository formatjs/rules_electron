# Signing stages

`//electron/tools:osslsigncode` builds pinned osslsigncode 2.15 directly from nine
C sources with native Bazel rules, OpenSSL 3.5.9 and zlib. Fixed Linux feature
headers replace source configure probes. OpenSSL's BCR overlay compiles C and
assembly from declared sources; its pregenerated headers/assembly are immutable
registry inputs. No CMake, Make, Meson or foreign-cc action runs. Full transitive
action audit: 1,783 C/C++ compiles, 28 links, zero forbidden mnemonics.

BB test uses the source-built OpenSSL CLI to create an ephemeral test-only key
and certificate inside its test sandbox. It signs a public upstream PE fixture
twice with an explicit signing time, compares bytes, verifies against that
certificate and rejects modified executable section data. Test keys never become
release artifacts. Hosted compilation and test results remain pending.

This tool is groundwork, not production signing policy. Release interfaces still
need credential/service isolation, certificate identity checks, Authenticode trust
on native Windows, timestamp policy, final-artifact ordering and MSIX deployment
proof. Production credentials must stay outside ordinary cacheable build actions.
macOS Developer ID/notarization/stapling and publication remain separate gaps.

Upstream signer, format support and license:
[osslsigncode](https://github.com/mtrojnar/osslsigncode/tree/b8fddbcd64733150181ae72a96bdd528d2fb4ea1).
