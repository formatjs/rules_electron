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
release artifacts. The
[b4e6938 BB suite](https://formatjs.buildbuddy.io/invocation/8fd6dde4-d5f7-40fe-8bd3-d4f828417763)
passed actual PE signing, byte reproducibility, verification and section-tamper
rejection.

The [23f7167 suite](https://formatjs.buildbuddy.io/invocation/feb26e4f-2453-4ff3-ab50-81f58c7dd10e)
also signs native `create_msix` output and verifies its signature. It checks
unchanged payload/blockmap bytes, final PKCX signature entry, matching ZIP64
local/central sizes and byte-identical repeat signing. Two pinned signer patches
repair stale local ZIP64 sizes when rewriting footprint XML and fix signature
ZIP metadata at 1980-01-01; signed attributes retain the explicit signing time.
This is BB cryptographic round-trip proof, not native Windows trust/deployment
proof.

This tool is groundwork, not production signing policy. Release interfaces still
need credential/service isolation, certificate identity checks, Authenticode trust
on native Windows, timestamp policy, final-artifact ordering and MSIX deployment
proof. Production credentials must stay outside ordinary cacheable build actions.
macOS Developer ID/notarization/stapling and publication remain separate gaps.

Upstream signer, format support and license:
[osslsigncode](https://github.com/mtrojnar/osslsigncode/tree/b8fddbcd64733150181ae72a96bdd528d2fb4ea1).
