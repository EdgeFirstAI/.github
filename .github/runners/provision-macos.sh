#!/usr/bin/env bash
# Provision an ephemeral macOS GitHub Actions runner.
# Labels: self-hosted, macos, arm64, metal
#
# Required env: RUNNER_TOKEN
# Optional: GITHUB_ORG, RUNNER_NAME, RUNNER_LABELS, RUNNER_GROUP, WORKDIR, RUNNER_VERSION

set -euo pipefail

GITHUB_ORG="${GITHUB_ORG:-EdgeFirstAI}"
WORKDIR="${WORKDIR:-$HOME/actions-runner}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname)-mac}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,macos,arm64,metal}"
RUNNER_GROUP="${RUNNER_GROUP:-mac}"
VERSION="${RUNNER_VERSION:-2.328.0}"

if [[ -z "${RUNNER_TOKEN:-}" ]]; then
  echo "RUNNER_TOKEN is required" >&2
  exit 1
fi

mkdir -p "$WORKDIR"
cd "$WORKDIR"
if [[ ! -x ./config.sh ]]; then
  curl -fsSL -o actions-runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${VERSION}/actions-runner-osx-arm64-${VERSION}.tar.gz"
  tar xzf actions-runner.tar.gz
fi

./config.sh --unattended --replace \
  --url "https://github.com/${GITHUB_ORG}" \
  --token "$RUNNER_TOKEN" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABELS" \
  --runnergroup "$RUNNER_GROUP" \
  --work _work \
  --ephemeral

exec ./run.sh
