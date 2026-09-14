# Changelog

All notable changes to the EdgeFirstAI shared CI workflows are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `pre-command` input on `rust-quick` and `rust-full` host/board jobs so callers
  can install OpenCV, fetch ANGLE, or merge LFS testdata after checkout. The
  command is passed through `env`, never interpolated into the script text.
  Its environment contract is documented: the caller checkout as working
  directory, `GH_TOKEN` / `GITHUB_TOKEN` for `gh` and API calls, and
  `GITHUB_ENV` / `GITHUB_PATH` for exporting state. Secrets are not passed.
- `rust-quick` splits the old all-or-nothing `python` input: `python` runs ruff
  lint, `python-tests` adds the maturin develop + pytest pass, and `ruff-paths`
  targets specific directories. hal needed lint without the test pass and had
  to hand-roll a job for it.
- `check_license_policy.py --self-test` covers the SPDX evaluator against the
  expressions that have broken the fleet. The shared CI lint job runs it.
- `rust-full` `board-pre-command`, `board-extra-args`, and `archive-args` so
  on-target jobs can skip host package installs, run tests with `-j 1`, and
  archive a different feature set than the host matrix. Host linux-arm
  uploads merged LFS testdata as `ci-testdata` for the board to download.

### Changed

- Runner policy is now per tier rather than a single cost-first ordering.
  Quick stays on free standard runners and never bills; Full and Release
  default to `larger`, which is what they were before this migration. Moving
  those lanes to standard runners to save money made hal's Full tier slower
  than the 15-to-20-job workflow it replaced, which is a failed migration, not
  a saving. The `larger` class maps to `ubuntu-24.04-xlarge` /
  `ubuntu-24.04-arm-xlarge` to match the hosted class.

### Fixed

- LFS checkouts install `git-lfs` first when the runner image lacks it. The
  org-provisioned `ubuntu-24.04-arm-xlarge` image ships without it, so moving
  a lane from a standard runner to that class failed at checkout, before any
  repository code existed to repair it.
- `protect-release-tags` also blocks tag `update`. hal's hand-made repo ruleset
  had that rule and the org one did not, so retiring the duplicate would have
  widened what a `v*` tag allows.
- `apply.sh` no longer needs a standalone `jq` (absent from a stock Git Bash,
  which made it unrunnable on Windows) and discards API response bodies, which
  ran into the next ruleset's progress line.
- **License policy rejected valid dependencies.** The evaluator compared whole
  SPDX expressions against the allowlist, so any parenthesised compound failed:
  `(MIT OR Apache-2.0) AND Unicode-3.0` was rejected even though every term is
  allowed. cargo-cyclonedx emits exactly that shape, and it blocked hal's Quick
  tier. Replaced with a real expression evaluator (parentheses, nesting, `WITH`,
  `+`) where AND takes the worst operand and OR the best. `IJG`, dropped when
  the per-repo policies were consolidated, is allowed again.
- License identifiers are matched case-insensitively, per SPDX. Previously
  `gpl-3.0` missed the blocked-licence check and fell through to "unknown".
- Violation messages name the offending licence rather than the whole
  expression.
- `rust-full` Linux coverage no longer re-runs the whole suite on failure. The
  `--profile ci || retry` fallback was meant to cover a missing nextest profile
  but caught genuine test failures, doubling wall-clock before reporting them.
  The profile is now selected with `hashFiles`.
- `rust-full` uploads only the instrumented test binaries for board coverage
  instead of the entire `target/llvm-cov-target` tree.
- `rust-full`'s SonarCloud job passes the merged `coverage/lcov.info` to the
  scanner. It was building the file and never referencing it.
- Inner `pre-command` bash inherits `set -euo pipefail` (`bash --noprofile --norc -euo pipefail -c`).
- Caller `templates/ci.yml` treats `ci:full` / `ci:hardware` as sticky: Full
  re-runs on later pushes while the label is still present, not only on the
  `labeled` event.
- GitHub Release notes use `body_path`; `softprops/action-gh-release` v2.5.0
  ignores `body_file`, so v1.0.0 published with an empty body.
- Dependabot scans workflows and composites in one `directories` list with a
  single `actions` group, so weekly bumps land as one PR instead of one per
  composite. Caller templates pin
  `eec0cb31b6576a47735099b91e39a9bdb5fbde3a` (action bumps on main).
- Retired the `shared-sha` input. Shared workflows resolve their own repository
  and commit from `job.workflow_repository` / `job.workflow_sha` to reach their
  composite actions, so the shared commit appears only in the caller's `uses:`
  pin, Dependabot's bump is complete on its own, and the two values can no
  longer drift. The earlier attempt needed the input because
  `github.workflow_sha` is the *caller's* commit, not this repository's.
- Full scancode writes native JSON and converts it to CycloneDX, and pins
  Click 8.2. ScanCode 32.4.1 plus Click 8.5 treats `--full-root` and
  `--strip-root` as both set. The converter keeps ScanCode's PURL `bom-ref`
  plus group, author, copyright, description, hashes and external
  references so cargo-cyclonedx and source scans dedupe. Dependency SBOM
  merge ignores `venv/` so ScanCode's bundled `*.cdx.json` fixtures are
  not treated as crate components.

## [1.0.0] - 2026-09-11

### Added

- Reusable workflows: `rust-quick`, `rust-full`, `python-quick`, `cmake-quick`,
  `nightly-gate`, `sbom`, `tag-release`, `release-rust`.
- Composite actions: `setup-rust`, `setup-python-uv`, `sbom-tools`, `board-run`.
- Canonical license policy scripts and `copilot-instructions.md`.
- Org ruleset JSON, runner provision scripts, usage-report and runner-audit.
  Reviews (`protect-main`) allow org-admin PR merge without a human approval;
  `protect-main-ci` still requires `ci-gate` with no bypass. Tag protection
  (`protect-release-tags`) allows org-admin bypass only — GitHub Actions
  cannot be added as an org ruleset bypass actor.
- Per-repository caller templates.
- Python Quick and CMake Quick run the shared license policy (NOTICE is
  required; C/C++ dependency graphs remain Full scancode).

### Fixed

- Fork Full jobs force hosted runners; `skip-cross-clippy` no longer ignores
  its input; hardware-only Full skips scancode and SonarCloud.
- Hardware coverage archives objects under `target/llvm-cov-target` and fails
  the merge job when profraw or objects are missing.
- Release GitHub Release waits for SBOM/wheels/c-archive; tag `latest`
  selection paginates; SBOM copy no longer no-ops onto itself.
- Runner audit only inspects `runs-on` and paginates org repos; usage-report
  uses the current billing usage-summary API.
- Caller templates pin `ca1dd553f352cbdf0d80c0abe2d52237c6964f25` (`v1.0.0`
  workflow tree) and run Full once per label, with `ci:full` taking
  precedence over `ci:hardware`. PyPI publish requires the reusable release
  job to succeed.

[Unreleased]: https://github.com/EdgeFirstAI/.github/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/EdgeFirstAI/.github/releases/tag/v1.0.0
