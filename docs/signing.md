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
need credential/service isolation, certificate identity checks, production trust
and timestamp policy, final-artifact ordering and source-built Electron MSIX deployment
proof. Production credentials must stay outside ordinary cacheable build actions.
macOS Developer ID/notarization/stapling and publication remain separate gaps.

Upstream signer, format support and license:
[osslsigncode](https://github.com/mtrojnar/osslsigncode/tree/b8fddbcd64733150181ae72a96bdd528d2fb4ea1).

Signed MSIX native fixtures are now wired for Windows x64/ARM64. BB builds a
fixed `CN=Example` certificate from OpenSSL's public `ee-key.pem` test vector,
with explicit 2026–2036 validity, serial and code-signing extensions. No random
key or wall clock enters fixture build outputs. BB signs twice, compares bytes,
verifies the signature and emits a deliberately corrupted package. Native smoke
checks unsigned/untrusted rejection, trusted signature and bad-digest rejection,
then installs, executes the packaged helper and removes it. The temporary
LocalMachine TrustedPeople certificate is removed in `finally`, following
[Microsoft's test-certificate guidance](https://learn.microsoft.com/en-us/windows/msix/package/create-certificate-package-signing).
The [1aae3c3 BB suite](https://formatjs.buildbuddy.io/invocation/e8530349-31bc-47c7-8356-c6e0766507d7)
passed certificate reproducibility, subject/issuer, validity, code-signing purpose
and chain verification. Cross-build hit GitHub browser-download timeouts for
`rules_perl` 2.0.0 and OpenSSL's pregenerated-source archive. BB prefetches both
through fixed official GitHub release-asset API IDs, verifies their unchanged
BCR SHA-256 hashes, then passes them to Bazel through `--distdir`. The zlib
1.3.2 download uses upstream's byte-identical fossil archive.
This only fetches immutable sources; compilers and package generators still run
as declared Bazel actions.

The [1909e3b BB suite](https://formatjs.buildbuddy.io/invocation/80d0f8fa-c8b3-48b8-9b64-a87f4e338a8e)
and [cross-build](https://formatjs.buildbuddy.io/invocation/9094cc22-1549-4470-93ea-90c07dede702)
passed. Native [Windows x64](https://github.com/formatjs/rules_electron/actions/runs/42571326791/job/129009330403)
and [ARM64](https://github.com/formatjs/rules_electron/actions/runs/42571326791/job/129009330204)
passed exact WinVerifyTrust results: unsigned `0x800b0100`, untrusted root
`0x800b0109`, trusted success `0x00000000`, changed payload `0x80096010`.
Both installed the signed package, executed its native helper, removed the
package and removed the temporary certificate. No runtime compilation or signing
occurs on those hosts. The subsequent [full-app MSIX gate](msix.md) also passed
bootstrap Electron installation and upgrades on both Windows CPUs. Production
credential/service interfaces and the complete source-built runtime remain open.

`@rules_electron//electron/tools:sign_windows` provides an explicit Linux release
command for PE and MSIX artifacts. It carries the source-built signer in its
runfiles; it never discovers a host signer. Run it on the BB release client,
outside ordinary cacheable artifact actions:

```sh
bazel run --config=bb-workflow @rules_electron//electron/tools:sign_windows -- \
  --input "$unsigned_artifact" --output "$signed_artifact" \
  --certificate-env RELEASE_CERT_FILE --key-env RELEASE_KEY_FILE \
  --password-env RELEASE_KEY_PASSWORD --ca-file release-roots.pem \
  --expected-leaf-sha256 "$release_certificate_sha256" \
  --signing-time "$release_signing_time" \
  --timestamp-url https://timestamp.example.com/ \
  --https-ca-file https-roots.pem --tsa-ca-file timestamp-roots.pem
```

Certificate/key environment variables contain private file paths. The optional
password variable contains the key password, passed to the signer through stdin.
Credentials never enter rule attributes, build action environments or outputs.
The child environment contains no inherited credentials or OpenSSL configuration;
backend messages are suppressed. Trust roots and expected leaf identity are
explicit. Signing snapshots the input, verifies final bytes and certificate
identity, then atomically creates a new output without overwriting existing files.
Generate update metadata and blockmaps from that final output.

RFC 3161 timestamps require HTTPS, explicit transport/TSA roots and successful
timestamp verification. `--no-timestamp` is an explicit alternative for test or
deliberately untimestamped releases; it is never selected implicitly. Hosted
interface tests cover real PE/MSIX signing, encrypted keys, repeatability,
identity/trust rejection, output preservation and final updater hashes. Validation
is pending for the added local HTTPS RFC 3161 exchange and rejection tests.
The [5d18260 BB suite](https://formatjs.buildbuddy.io/invocation/788bc1e4-d72b-43ae-b3a7-e696ec1b1aec)
passed the public PE/MSIX interface, encrypted keys, identity/trust rejection,
repeat signing and final feed hashes; its
[cross-build](https://formatjs.buildbuddy.io/invocation/5f1f18a2-ca08-419e-bd3e-ad6755d67d6e)
also passed. A narrow native signer patch adds TLS hostname checks and makes
invalid explicit transport roots fail instead of skipping verification.
Live TSA interoperability, production trust, credential services,
certificate rotation/revocation policy and native Windows release acceptance
remain open; this command does not establish those claims.
