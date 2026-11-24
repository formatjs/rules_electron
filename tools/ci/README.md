# CI

GitHub Actions orchestrates tests and cross-builds on BuildBuddy, using the same
organization keys and trust boundary as
[gazelle_rs](https://github.com/perplexityai/gazelle_rs/blob/main/.github/ci/README.md).
Builds use `remote.buildbuddy.io`; invocation links use `app.buildbuddy.io`.
The hosted `buildbuddy.yaml` workflow is retired.

`BB_RO_KEY` is an organization Actions variable, exposed to this repository and
fork PRs. Its BuildBuddy permissions must allow CAS reads/writes and AC reads,
without AC writes (Developer permissions, not a strictly read-only Reader key).
PRs, merge queues, manual runs and artifact diagnostics use this key. Local-result
uploads default off; server-side key permissions enforce the action-cache boundary.

`BB_RW_KEY` is the organization writer key stored as a secret in this repository's
`ci` environment. Restrict that environment's deployment branches to `main`.
Do not expose this writer as a repository-wide or organization-wide Actions secret:
PR-authored workflows could request it. The workflow and Bazel wrapper both limit
writer use to a push to `main` in `perplexityai/rules_electron`; the wrapper also
checks the actual checkout matches the event SHA. A main push fails if the writer
is missing. Untrusted builds fail if the public key is missing, without falling
back to local compilation.

Enable organization-variable access to this repository, provision the protected
`ci` environment and its writer secret, then make `CI` the required branch check.
Remove the retired hosted-workflow checks from branch protection during cutover.
Never commit key values. Local users can supply credentials in ignored
`.bazelrc.user`; the CI wrapper is only installed by GitHub Actions.

Cross-build jobs download BB outputs and relay four archives as GitHub artifacts.
Reusable native smoke jobs consume artifacts from that same workflow run,
bound to the caller's commit; Linux x64, macOS ARM64 and Windows x64/ARM64
hosts execute them without Bazel. Linux ARM64 remains cross-build only. Manual
BB diagnostics still validate invocation repository, commit, workflow and digest.
Manual native execution requires the invocation commit to match the selected
workflow revision; log diagnostics can inspect other commits. Native harnesses
always come from the workflow revision, never an arbitrary input checkout.

The `CI` check requires tests, cross-builds and all four native smoke jobs to
succeed. Electron comes from the example's integrity-pinned official prebuilts;
no source-overlay checkout or source-runtime build is part of this pipeline.
Packaging tools and native addons still use declared Bazel toolchains on BB.
Releases must not use the public CI action cache as a trusted release cache.
