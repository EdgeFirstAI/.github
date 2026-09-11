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

Apply in order; stop at the first fit:

1. **hosted** — `ubuntu-24.04`, `ubuntu-24.04-arm`, `macos-latest`,
   `windows-latest`. Default for Quick and for Full lanes under 20 minutes.
2. **fleet** — self-hosted groups `boards`, `build-x86`, `gpu-cuda`, `mac`,
   `windows`. Full and Nightly only. Never fork PRs; the shared Full workflow
   forces `hosted` when `head.repo` is not this repository.
3. **larger** — GitHub `-xlarge` / `-8core`. Exception only, via the caller
   input `runner-class-*: larger` with a comment naming the reason and review
   date. Group `larger-runners` is restricted to `hal` and `packaging`.

Never add a billed runner label in a workflow without `runner-class: larger`.
A nightly audit opens an issue when that happens.

## How to call the shared workflows

Pin the **commit SHA** of `EdgeFirstAI/.github` and record the tag in a comment:

```yaml
jobs:
  quick:
    uses: EdgeFirstAI/.github/.github/workflows/rust-quick.yml@<sha>  # v1.0.0
    with:
      python: true
  full:
    if: needs.changes.outputs.full == 'true'
    uses: EdgeFirstAI/.github/.github/workflows/rust-full.yml@<sha>  # v1.0.0
    with:
      lanes: all
      boards: nxp-imx8mp-latest
      runner-class-linux: hosted
    secrets: inherit
```

Copy the caller skeletons from [`templates/`](https://github.com/EdgeFirstAI/.github/tree/main/templates).
Repository-specific steps (ANGLE, LFS testdata, OpenCV, `vcan0`) become
**inputs**, not pasted jobs.

Inputs that matter:

- `rust-quick`: `python`, `timeout-minutes` (hal: 15), `cross-targets`, `runner`
- `rust-full`: `lanes` (`all` \| `host` \| `hardware`), `boards`, `nightly`,
  `runner-class-linux` / `-linux-arm` / `-macos` / `-windows`
- `sbom`: `mode` `dependency` \| `full`
- `release-rust`: `dry-run`, `publish-crates`, `build-wheels`

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
