# EdgeFirstAI shared CI

Reusable GitHub Actions for EdgeFirst and Maivin repositories. Product repos
call these workflows by **commit SHA** (tag recorded in a comment). This
repository is public so other public repos can `uses:` it.

Design: [CICD Pipelines](https://au-zone.atlassian.net/wiki/spaces/EAM/pages/2750906369/CICD+Pipelines)
Ticket: [EDGEAI-1553](https://au-zone.atlassian.net/browse/EDGEAI-1553)

The organisation profile README lives in [`profile/`](profile/README.md).

## Layout

| Path | Purpose |
| --- | --- |
| `.github/workflows/rust-quick.yml` | fmt, clippy, nextest, dependency license |
| `.github/workflows/rust-full.yml` | host matrix, boards, coverage, scancode |
| `.github/workflows/python-quick.yml` | ruff + pytest |
| `.github/workflows/cmake-quick.yml` | ccache + ctest |
| `.github/workflows/nightly-gate.yml` | skip nightly when `main` is unchanged |
| `.github/workflows/sbom.yml` | `dependency` or `full` scancode |
| `.github/workflows/tag-release.yml` | `release/X.Y.Z` merge → annotated `vX.Y.Z` |
| `.github/workflows/release-rust.yml` | crates OIDC, wheels as artifacts, GitHub Release |
| `.github/actions/` | `setup-rust`, `setup-python-uv`, `sbom-tools`, `board-run` |
| `.github/scripts/` | license policy (single copy) |
| `.github/rulesets/` | `protect-main` (reviews; org-admin PR bypass), `protect-main-ci` (ci-gate, no bypass), `protect-release-tags` |
| `.github/runners/` | ephemeral fleet provision scripts |
| `templates/` | per-repo `ci.yml`, `nightly.yml`, `tag-release.yml`, `release.yml` |

## Pinning

```yaml
uses: EdgeFirstAI/.github/.github/workflows/rust-quick.yml@<sha>  # v1.0.0
```

Dependabot `github-actions` in each product repo bumps the SHA. Caller
templates ship a 40-character placeholder SHA that must be replaced before
use; CI rejects tag refs such as `@v1.0.0`.

## Tiers and labels

- **Quick** — every non-draft PR push.
- **Full** — label `ci:full` (or `ci:hardware` for boards only).
- **Nightly** — schedule, only if `main` moved.

`ci-gate` is the only required check. See
[`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## Runner classes

Per-lane input `runner-class-linux` (and arm/mac/windows): `hosted` (default),
`fleet`, or `larger`. Billed GitHub larger runners are an exception recorded in
the caller and restricted by the `larger-runners` group.

## Release chain

1. PR `release/X.Y.Z` → `main` with `ci:full`.
2. Merge. Shared tag workflow creates an annotated `vX.Y.Z` using
   `RELEASE_TAG_TOKEN`.
3. Tag runs `release-rust.yml`. crates.io trusted publishing uses the **caller**
   `workflow_ref` and environment `crates-io`.
4. PyPI trusted publishing **cannot** use this reusable workflow. The caller
   keeps `publish-pypi` (see `templates/release.yml`).

Do not tag by hand. Org rulesets in `.github/rulesets/` enforce `ci-gate` on
migrated repos and restrict `v*` tag creation. Org admins may merge their own
PRs without a human approval; other authors still need a review. `ci-gate`
is required for everyone.

## Applying org settings

```bash
gh auth refresh -h github.com -s admin:org
bash .github/rulesets/apply.sh
```

Create runner groups from `.github/rulesets/runner-groups.md`. Register
machines with `.github/runners/provision-*.sh` (EDGEAI-1577).

Set organisation Copilot custom instructions to
`.github/copilot-instructions.md`.
