#!/usr/bin/env bash
# Provision the GitHub Actions runner agent onto EdgeFirstAI self-hosted
# boards: download the stock runner, register it with the organisation into
# the "boards" runner group, apply its family/board/capability labels, and
# enable it as a persistent boot service via svc.sh.
#
# Deliberately keeps no inventory of board names anywhere in this repository
# (this repo is EdgeFirstAI/.github, which is public). Group membership is
# set at registration via config.sh --runnergroup, and labels are derived
# on the fly from the board's own name using the family/identity/capability
# convention documented in Confluence (EAM "CICD Pipelines"), then applied
# straight to the GitHub API -- the runner's own registration is the only
# record that it exists; nothing about it is ever written to a file, public
# or private. "boards" itself and the family/capability vocabulary below are
# category names from that convention, not specific machines, so they are
# fine to keep in this public script. apply_runners.py / runners.json now
# manage only group-level settings (visibility, public-repository access)
# for every group, boards included -- no runner names live there either.
# Non-board runners (build-x86, gpu-cuda, windows, yocto) get their labels
# from a one-time `gh api` call at setup time, the same idea as this script
# but without a derivable naming pattern to automate it from.
#
# Registers with NO --labels on config.sh itself: the agent re-asserts
# whatever labels it was configured with on every reconnect, so a label set
# there would fight the API-applied ones over casing/content. Every custom
# label is applied via a POST after registration instead.
#
# Requires:
#   - gh authenticated with admin:org scope (same session apply_runners.py
#     uses) to mint a runner registration token. The token is minted here,
#     on the controller, and never persisted on the board -- config.sh
#     consumes it once and it is invalidated on use.
#   - SSH access to each board via the alias already in ~/.ssh/config. This
#     script never overrides the configured user: a board that logs in as
#     root gets RUNNER_ALLOW_RUNASROOT wired into both the registration
#     step and the service's .env (systemd does not inherit an exported
#     shell variable, so the service re-fails the same root check on every
#     start unless it is persisted there); a board that logs in as a
#     sudo-capable non-root user needs neither -- svc.sh install elevates
#     itself internally via sudo.
#
# The remote steps are sent as a heredoc over ssh's stdin rather than as
# command-line arguments, specifically so the registration token never
# appears in `ps` output on the controller.
#
# Usage:
#   provision_runner.sh [--dry-run] [--org ORG] [--version VER] [--replace] TARGET [TARGET...]
#
# TARGET is SSH_ALIAS or SSH_ALIAS=RUNNER_NAME. SSH_ALIAS is how the board is
# reached (an alias in ~/.ssh/config) and is just a hostname -- it carries no
# convention meaning of its own. RUNNER_NAME is the board identity labels are
# derived from (family[-board][-equipment], per runner-groups.md's label
# convention) and defaults to SSH_ALIAS when omitted. The two are frequently
# not the same string: an SSH alias like `rpi5-hailo` is whatever the box
# happened to get called, but the board identity per convention is
# `rpi5-hailo8l` (family `rpi5` plus equipment `hailo8l`) -- pass
# `rpi5-hailo=rpi5-hailo8l` to reach the former and register/label the
# latter. The board's own on-device `hostname` is never used for either
# purpose: several boards share a build hostname (both Ezurio units report
# "summit"), and GitHub runner names must be unique per org.

set -euo pipefail

ORG="EdgeFirstAI"
RUNNER_VERSION=""
MIN_VERSION="2.336.0"
DRY_RUN=0
REPLACE=0
HOSTS=()

usage() {
  cat >&2 <<'EOF'
Usage: provision_runner.sh [--dry-run] [--org ORG] [--version VER] [--replace] TARGET [TARGET...]
TARGET is SSH_ALIAS or SSH_ALIAS=RUNNER_NAME (see header comment).
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --org) ORG="$2"; shift 2 ;;
    --version) RUNNER_VERSION="$2"; shift 2 ;;
    --replace) REPLACE=1; shift ;;
    -h|--help) usage ;;
    --) shift; break ;;
    -*) echo "unknown flag: $1" >&2; usage ;;
    *) HOSTS+=("$1"); shift ;;
  esac
done
[[ ${#HOSTS[@]} -gt 0 ]] || usage

command -v gh >/dev/null 2>&1 || { echo "gh CLI is required" >&2; exit 1; }

RUNNER_GROUP="boards"

# Known family prefixes and capability-suffix vocabulary from the org's
# runner-label convention. These are category/taxonomy names, not specific
# machines, so listing them here does not name any target.
BOARD_FAMILIES=(imx8mp imx95 rpi5 rk3855 orin)
CAPABILITY_SUFFIXES=(hailo8l ara240)

# Derives labels for a board purely from its own name, one per line: the
# bare family, the full name as board identity, and a bare capability label
# when the last hyphen-segment matches the known vocabulary. Prints nothing
# (and the caller must skip labeling) if the name doesn't match a known
# family -- that's a signal the name doesn't follow convention, not
# something to guess at.
board_labels() {
  local name="$1" family="" f last
  for f in "${BOARD_FAMILIES[@]}"; do
    if [[ "$name" == "$f" || "$name" == "$f"-* ]]; then
      family="$f"
      break
    fi
  done
  if [[ -z "$family" ]]; then
    echo "    warning: '$name' does not match a known board-family prefix (${BOARD_FAMILIES[*]}) -- not applying automatic labels" >&2
    return
  fi
  printf '%s\n' "$family" "$name"
  last="${name##*-}"
  for f in "${CAPABILITY_SUFFIXES[@]}"; do
    if [[ "$last" == "$f" ]]; then
      printf '%s\n' "$last"
      break
    fi
  done
  return 0
}

# Resolve once, centrally, so every board in this run gets the identical
# build -- drift is caught here, not discovered later as nine slightly
# different agents.
if [[ -z "$RUNNER_VERSION" ]]; then
  RUNNER_VERSION="$(gh api repos/actions/runner/releases/latest --jq '.tag_name' | sed 's/^v//')"
fi
echo "==> runner version: $RUNNER_VERSION"
if ! printf '%s\n%s\n' "$MIN_VERSION" "$RUNNER_VERSION" | sort -C -V; then
  echo "runner $RUNNER_VERSION is older than $MIN_VERSION, the minimum this org's shared workflows require (the \$/ self-reference syntax)" >&2
  exit 1
fi

RELEASE_BODY="$(gh api "repos/actions/runner/releases/tags/v${RUNNER_VERSION}" --jq '.body')"
CHECKSUM="$(printf '%s' "$RELEASE_BODY" | sed -n 's/.*BEGIN SHA linux-arm64 -->\([a-f0-9]*\)<!-- END.*/\1/p')"
if [[ -z "$CHECKSUM" ]]; then
  echo "could not find a linux-arm64 SHA-256 in the v${RUNNER_VERSION} release notes -- refusing to provision without an integrity check" >&2
  exit 1
fi
echo "==> linux-arm64 sha256: $CHECKSUM"

TARBALL="actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"

declare -A RESULT

for target in "${HOSTS[@]}"; do
  ssh_host="${target%%=*}"
  if [[ "$target" == *=* ]]; then
    runner_name="${target#*=}"
  else
    runner_name="$ssh_host"
  fi

  echo
  echo "==> $ssh_host (runner name: $runner_name)"

  if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$ssh_host" true 2>/dev/null; then
    echo "    unreachable -- skipping"
    RESULT[$target]="UNREACHABLE"
    continue
  fi

  already="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$ssh_host" \
    'test -f "$HOME/actions-runner/.runner" && echo yes || echo no' 2>/dev/null)"
  if [[ "$already" == "yes" && "$REPLACE" -eq 0 ]]; then
    echo "    already registered (\$HOME/actions-runner/.runner present) -- skipping, use --replace to reconfigure"
    RESULT[$target]="ALREADY_REGISTERED"
    continue
  fi

  labels="$(board_labels "$runner_name" | paste -sd, -)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    would download $TARBALL, verify sha256, register as '$runner_name' into group '$RUNNER_GROUP'"
    echo "    would apply labels: ${labels:-<none -- name did not match a known family>}"
    echo "    would install+start the svc.sh service"
    RESULT[$target]="DRY_RUN"
    continue
  fi

  echo "    minting registration token"
  TOKEN="$(gh api -X POST "orgs/${ORG}/actions/runners/registration-token" --jq .token)"

  # Sent over ssh's stdin, not as a command-line argument -- keeps the
  # token out of `ps` on the controller. It still appears briefly in `ps`
  # on the *board* while config.sh runs, which is inherent to how the
  # runner's own CLI takes it and not something this script can avoid.
  if ssh -o BatchMode=yes -o ConnectTimeout=10 "$ssh_host" bash -s <<REMOTE
set -euo pipefail
cd "\$HOME"
mkdir -p actions-runner
cd actions-runner

if [[ ! -f "$TARBALL" ]]; then
  if command -v wget >/dev/null 2>&1; then
    wget -q -O "$TARBALL" "$DOWNLOAD_URL"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$TARBALL" "$DOWNLOAD_URL"
  else
    echo "neither wget nor curl is available" >&2
    exit 1
  fi
fi

echo "$CHECKSUM  $TARBALL" | sha256sum -c - >/dev/null

tar xzf "$TARBALL"

RUNAS_ROOT=0
if [[ "\$(id -u)" -eq 0 ]]; then
  RUNAS_ROOT=1
  export RUNNER_ALLOW_RUNASROOT=1
fi

./config.sh --url "https://github.com/${ORG}" --token "$TOKEN" \
  --name "$runner_name" --runnergroup "$RUNNER_GROUP" --work _work --unattended --replace

if [[ "\$RUNAS_ROOT" -eq 1 ]] && ! grep -qs '^RUNNER_ALLOW_RUNASROOT=1\$' .env 2>/dev/null; then
  echo "RUNNER_ALLOW_RUNASROOT=1" >> .env
fi

# svc.sh (verified against actions/runner's systemd.svc.sh.template) hard-
# requires id -u == 0 and never elevates itself -- it is a wrapper around
# systemctl, not a sudo-aware installer. A board already logged in as root
# must call it directly: some of these boards have no sudo binary at all,
# and passing "root" explicitly avoids install's own fallback (arg2, else
# \$SUDO_USER) landing on an *empty* string when SUDO_USER is unset, which
# would substitute an empty User= into the generated unit instead of
# User=root. A non-root login has no such ambiguity to avoid, but still
# needs sudo since svc.sh itself refuses to self-elevate.
if [[ "\$RUNAS_ROOT" -eq 1 ]]; then
  ./svc.sh install root
  ./svc.sh start
  ./svc.sh status
else
  sudo ./svc.sh install
  sudo ./svc.sh start
  sudo ./svc.sh status
fi
REMOTE
  then
    echo "    provisioned and service started; applying labels"
    runner_id="$(gh api "orgs/${ORG}/actions/runners" --paginate \
      --jq ".runners[] | select(.name==\"$runner_name\") | .id" | head -1)"
    if [[ -z "$runner_id" ]]; then
      echo "    WARNING: registered but could not look up its runner id -- labels not applied"
      RESULT[$target]="OK_NO_LABELS"
    else
      current="$(gh api "orgs/${ORG}/actions/runners/${runner_id}" \
        --jq '.labels[] | select(.type=="custom") | .name')"
      while IFS= read -r label; do
        [[ -z "$label" ]] && continue
        if printf '%s\n' "$current" | grep -qix -- "$label"; then
          continue
        fi
        gh api --method POST "orgs/${ORG}/actions/runners/${runner_id}/labels" \
          -f "labels[]=$label" >/dev/null
        echo "    applied label: $label"
      done < <(board_labels "$runner_name")
      RESULT[$target]="OK"
    fi
  else
    echo "    FAILED -- see output above"
    RESULT[$target]="FAILED"
  fi
done

echo
echo "==> summary"
for target in "${HOSTS[@]}"; do
  printf '    %-28s %s\n' "$target" "${RESULT[$target]:-UNKNOWN}"
done
