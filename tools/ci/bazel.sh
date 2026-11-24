#!/usr/bin/env bash
set -euo pipefail

startup=()
while [[ $# -gt 0 && "$1" == -* ]]; do
  startup+=("$1")
  shift
done
[[ $# -gt 0 ]] || exec "${BAZEL_REAL:?}" "${startup[@]}"
command=$1
shift

case "$command" in
  build|test|run|coverage|fetch|aquery|cquery)
    : "${BB_RO_KEY:?CI requires the public BuildBuddy key BB_RO_KEY}"
    key=$BB_RO_KEY
    upload=--noremote_upload_local_results
    if [[ "${GITHUB_EVENT_NAME:-}" == push && "${GITHUB_REF:-}" == refs/heads/main &&
          "${GITHUB_REPOSITORY:-}" == perplexityai/rules_electron &&
          "$(git -C "${GITHUB_WORKSPACE:?}" rev-parse HEAD)" == "${GITHUB_SHA:-}" ]]; then
      : "${BB_RW_KEY:?Main CI requires the BuildBuddy writer key BB_RW_KEY}"
      key=$BB_RW_KEY
      upload=--remote_upload_local_results
    fi
    contents_cache=()
    # Repository contents may retain toolchain symlinks into previous agents.
    if [[ "$(cat "$GITHUB_WORKSPACE/.bazelversion")" == 9.* ]]; then
      contents_cache=(--repo_contents_cache=)
    fi
    exec "${BAZEL_REAL:?}" "${startup[@]}" "$command" --config=bb-workflow \
      "--remote_header=x-buildbuddy-api-key=$key" \
      "--bes_header=x-buildbuddy-api-key=$key" \
      "${contents_cache[@]}" "$upload" \
      "--build_metadata=COMMIT_SHA=${GITHUB_SHA:?}" \
      "--build_metadata=CI_RUN_ID=${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}" "$@"
    ;;
  *) exec "${BAZEL_REAL:?}" "${startup[@]}" "$command" "$@" ;;
esac
