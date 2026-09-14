# Changelog

All notable changes to the EdgeFirstAI shared CI workflows are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `pre-command` input on `rust-quick` and `rust-full` host/board jobs so callers
  can install OpenCV, fetch ANGLE, or merge LFS testdata after checkout. The
  command is passed through `env`, never interpolated into the script text.
- `rust-full` `board-pre-command`, `board-extra-args`, and `archive-args` so
  on-target jobs can skip host package installs, run tests with `-j 1`, and
  archive a different feature set than the host matrix. Host linux-arm
  uploads merged LFS testdata as `ci-testdata` for the board to download.

### Fixed

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
- Shared workflows take a required `shared-sha` input (same commit as the
  `uses:` pin) to check out composites. `github.workflow_sha` is not a git
  commit and `github.workflow_ref` is the caller workflow.
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
