#!/usr/bin/env bash
# Provision an ephemeral Linux GitHub Actions runner in a container.
# Labels: self-hosted, linux, x64, build  (add cuda on GPU hosts).
#
# Required env:
#   GITHUB_ORG          default EdgeFirstAI
#   RUNNER_TOKEN        registration token (org or repo)
#   RUNNER_NAME         hostname-based default
# Optional:
#   RUNNER_LABELS       default: self-hosted,linux,x64,build
#   RUNNER_GROUP        default: build-x86
#   WORKDIR             default: /opt/actions-runner

set -euo pipefail

GITHUB_ORG="${GITHUB_ORG:-EdgeFirstAI}"
WORKDIR="${WORKDIR:-/opt/actions-runner}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname)-linux}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,linux,x64,build}"
RUNNER_GROUP="${RUNNER_GROUP:-build-x86}"
VERSION="${RUNNER_VERSION:-2.328.0}"

if [[ -z "${RUNNER_TOKEN:-}" ]]; then
  echo "RUNNER_TOKEN is required (org registration token)" >&2
  exit 1
fi

sudo mkdir -p "$WORKDIR" /var/cache/sccache /var/cache/cargo
sudo chown -R "$(id -u)":"$(id -g)" "$WORKDIR" /var/cache/sccache /var/cache/cargo || true

cd "$WORKDIR"
if [[ ! -x ./config.sh ]]; then
  curl -fsSL -o actions-runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${VERSION}/actions-runner-linux-x64-${VERSION}.tar.gz"
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

# Persistent caches only; checkout is always ephemeral with --ephemeral.
export SCCACHE_DIR="${SCCACHE_DIR:-/var/cache/sccache}"
export CARGO_HOME="${CARGO_HOME:-/var/cache/cargo}"

exec ./run.sh
