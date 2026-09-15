# AI assistant guidelines (canonical)

This file is the organisation-wide process, CI and release guide for EdgeFirst
and Maivin repositories. Product repositories keep a short stub that links here
and then lists only project-specific layout, tests and hardware notes.

Source of truth: [EdgeFirstAI/.github/.github/copilot-instructions.md](https://github.com/EdgeFirstAI/.github/blob/main/.github/copilot-instructions.md)
Design: [CICD Pipelines](https://au-zone.atlassian.net/wiki/spaces/EAM/pages/2750906369/CICD+Pipelines)

## Git workflow

- Every change starts from a JIRA ticket. Branch from `main`:
  `feature/EDGEAI-123-short-description`, `bugfix/EDGEAI-123-…`,
  `release/X.Y.Z` (three numeric fields, no suffix).
- Commits: `EDGEAI-123: Imperative summary` plus DCO (`git commit -s`).
- Land via pull request. Do not push to `main` or create `v*` tags by hand.
- Authors who are not organisation admins need one approving review
  (CODEOWNERS on owned paths). Organisation admins may merge their own PRs
  without a human approval and may rely on Copilot code review. `ci-gate`
  is still required for every merge, including admin merges.
- Open long-running work as **draft** PRs. Drafts run no CI. Mark ready when
  you want the Quick tier.

## CRITICAL: stay at the repository root

Do not `cd` into subdirectories. Cargo, cmake, uv and git all accept paths
from the root; changing directory loses assistant context.

## Three CI tiers

| Tier | When | What |
| --- | --- | --- |
| **Quick** | every non-draft PR push | fmt, lint, check, host tests, dependency license policy (NOTICE required; C/C++ graphs wait for Full scancode). Target under 10 minutes (hal 15). |
| **Full** | `ci:full` or `ci:hardware` label, `workflow_dispatch`, or merge queue | platform matrix, boards, coverage, scancode. Once per PR, not once per push. |
| **Nightly** | schedule, only if `main` moved | Full plus slow suites. Quiet days cost nothing. |

Labels:

- `ci:full` — run the Full host matrix (and boards when configured).
- `ci:hardware` — run only the on-target lane and its aarch64 archive.
- Legacy `test-hardware` is replaced by `ci:hardware`.

Add `ci:full` before approving when the PR touches build/workflows, `unsafe`,
FFI, GL/G2D/DMA, platform `cfg`, dependency versions or public API. Skip it for
docs, comments and test-only refactors with green Quick. When in doubt, label.

Branch protection requires exactly one check: **`ci-gate`**. Path filters may
skip Quick; the gate still runs and treats `skipped` as success.

## Runner selection policy

The tier decides, not the job. What is being optimised differs per tier:

| Tier | Optimise for | Runner class |
| --- | --- | --- |
| **Quick** | cost **and** speed | `hosted` — free standard runners, always |
| **Full** | speed, cost accepted | `larger` |
| **Release** | speed, cost accepted | `larger` |
| **Nightly** | speed, cost accepted | `larger` (nothing blocks on it; see below) |

1. **hosted** — `ubuntu-24.04`, `ubuntu-24.04-arm`, `macos-latest`,
   `windows-latest`. Free and unmetered on public repositories. This is the
   Quick tier everywhere, with no exceptions: the per-push path never bills.
2. **larger** — `ubuntu-24.04-xlarge`, `ubuntu-24.04-arm-xlarge`,
   `macos-latest-xlarge`, `windows-latest-8-cores`, via
   `runner-class-*: larger`. The default for Full and Release. These tiers run
   once per PR or per tag, not per push, so the spend is bounded by review
   cadence rather than by typing. A Full tier that is slower than the pipeline
   it replaced is a failed migration, not a saving.
3. **fleet** — self-hosted groups `boards`, `build-x86`, `gpu-cuda`, `mac`,
   `windows`. Full and Nightly only. Never fork PRs; the shared Full workflow
   forces `hosted` when `head.repo` is not this repository. Phase 2 moves the
   Linux, Windows and CUDA lanes here and retires those larger runners; macOS
   stays billed because a hosted Apple runner has no free equivalent.

Putting a Quick lane on a billed runner is the defect the nightly audit exists
to catch. A Full or Release lane on a billed runner is the intended state; when
such a lane names the label directly rather than going through
`runner-class-*`, put `# runner-class: larger` in the file with the reason so
the audit can tell the two apart.

## How to call the shared workflows

Pin the **commit SHA** of `EdgeFirstAI/.github` and record the tag in a comment:

```yaml
jobs:
  quick:
    uses: EdgeFirstAI/.github/.github/workflows/rust-quick.yml@eec0cb31b6576a47735099b91e39a9bdb5fbde3a
    with:
      python: true
  full:
    if: needs.changes.outputs.full == 'true'
    uses: EdgeFirstAI/.github/.github/workflows/rust-full.yml@eec0cb31b6576a47735099b91e39a9bdb5fbde3a
    with:
      lanes: all
      boards: nxp-imx8mp-latest
      runner-class-linux: hosted
    secrets: inherit
```

The `uses:` pin is the only place the shared commit appears. The shared
workflows resolve their own repository and commit from `job.workflow_repository`
and `job.workflow_sha` to reach their composite actions, so there is no second
SHA to keep in sync and Dependabot's bump is complete on its own.

Copy the caller skeletons from [`templates/`](https://github.com/EdgeFirstAI/.github/tree/main/templates).
Repository-specific steps (ANGLE, LFS testdata, OpenCV, `vcan0`) become
**inputs**, not pasted jobs.

Inputs that matter:

- `rust-quick`: `python` (ruff lint), `python-tests` (adds maturin develop + pytest),
  `ruff-paths`, `timeout-minutes` (hal: 15), `cross-targets`, `runner`,
  `pre-command` (caller setup after checkout)
- `rust-full`: `lanes` (`all` \| `host` \| `hardware`), `boards`, `nightly`,
  `runner-class-linux` / `-linux-arm` / `-macos` / `-windows`, `pre-command` (host jobs),
  `board-pre-command` (board; falls back to `pre-command`), `board-extra-args` (`-j 1` and similar; not used for archive),
  `archive-args` (nextest archive features/packages; empty uses `nextest-args`)
- `sbom`: `mode` `dependency` \| `full`
- `release-rust`: `dry-run`, `publish-crates`, `build-wheels`

### The `pre-command` hook

Repository setup that cannot be expressed as an input (install OpenCV, fetch
ANGLE, merge LFS testdata) goes in a script in the calling repository, named by
`pre-command`. It runs after both checkouts and before the toolchain setup.

The command string is passed to the step through `env` and executed with
`bash --noprofile --norc -euo pipefail -c "$PRE_COMMAND"`. It is never
interpolated into the script text, so a caller cannot inject steps.

What a pre-command may rely on:

- the caller's checkout as the working directory;
- `GH_TOKEN` and `GITHUB_TOKEN`, set to the job's `github.token`, for `gh` and
  API calls such as release-asset downloads;
- `GITHUB_ENV` and `GITHUB_PATH` to export state to later steps.

Nothing else is guaranteed. Secrets are **not** passed to the hook; a step that
needs one belongs in the calling repository's own workflow.

The hook runs code from the pull request's head, so on a fork PR it is
attacker-controlled. That is the same exposure as `build.rs` or any test, and
it is why `rust-full` forces hosted runners and disables board lanes for fork
PRs. Never add a self-hosted lane that skips that guard.

Every job in the shared workflows has `timeout-minutes`. Every third-party
action is SHA-pinned. Do not reintroduce unpinned tags or jobs without a timeout.

## Release chain

1. Branch `release/X.Y.Z`, bump versions and CHANGELOG, open a PR to `main`.
2. Label `ci:full`. `verify-version` runs on `release/**` heads.
3. Merge the PR. The shared `tag-release.yml` creates an **annotated** `vX.Y.Z`
   tag at the merge commit using `RELEASE_TAG_TOKEN`.
4. The tag starts `release.yml`, which calls `release-rust.yml` (crates via OIDC
   environment `crates-io`, wheels as artifacts, SBOM attached, GitHub Release
   from CHANGELOG). Maintenance tags never displace semver `latest`.
5. **Never tag by hand.** The one exception is a maintenance line cut from an
   older tag (`release/X.Y.Z` not merged to `main`); maintainers may create that
   tag through the OrganizationAdmin tag-ruleset bypass
   (`RELEASE_TAG_TOKEN` must be a token owned by an org admin).

### PyPI trusted publishing

PyPI matches `job_workflow_ref` in the **publisher repository**. A reusable
workflow in `EdgeFirstAI/.github` cannot be a Trusted Publisher
([docs](https://docs.pypi.org/trusted-publishers/troubleshooting/)).
`release-rust.yml` **builds** wheels and uploads them. Each repo's `release.yml`
keeps a small `publish-pypi` job with `pypa/gh-action-pypi-publish` and
environment `pypi`. Composite actions are fine inside that job. crates.io
**does** work from the shared workflow (caller `workflow_ref`).

## License policy (zero tolerance)

Pre-approved: MIT, Apache-2.0, BSD-2/3-Clause, ISC, Unlicense, CC0-1.0, MPL-2.0
and the additional SPDX ids in `.github/scripts/check_license_policy.py`.
LGPL is forbidden in Rust (static linking). GPL/AGPL/SSPL are blocked.
NXP proprietary is allowed only when documented in NOTICE.
Do not wrap license checks in `|| true` or `continue-on-error`.

Use the shared `sbom-tools` action; do not keep a private copy of
`generate_sbom.sh` / `check_license_policy.py` / `validate_notice.py`.

## Code quality and security

- `cargo fmt --check`, clippy `-D warnings`, `--locked` everywhere.
- No secrets in the tree. Hash-pin GitHub Actions.
- CHANGELOG follows Keep a Changelog. Version files must match at release.

## Housekeeping

- PRs stay reviewable; prefer small diffs.
- Signed-off-by on every commit.
- Public API changes need a CHANGELOG entry in the same PR.
