# Changelog

All notable changes to the EdgeFirstAI shared CI workflows are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `advisories.yml`, a reusable workflow running `cargo audit`, meant to be called **without** `needs: changed` so the nightly gate does not skip it. Every other nightly lane asks a question about the code, so skipping an unchanged commit loses nothing; this one asks a question about the RustSec database, which changes daily whether the code does or not. Gated, it goes quiet exactly when a new advisory lands against a frozen `main` -- not hypothetical, since the 2026-09-15 nightly failed on RUSTSEC-2026-0204 against a `Cargo.lock` nobody had touched. It parses `Cargo.lock` without building and pins `ubuntu-24.04` rather than honouring the caller's `runner-class`, so a caller cannot accidentally put an every-night lane on a `larger` runner, which bills by the minute even on public repositories. Downgrade an advisory by committing `.cargo/audit.toml` in the calling repository.

- `hack-args` on `rust-full`, for the nightly `cargo hack check` feature-combination lane, defaulting to the previous hardcoded `--feature-powerset --depth 2`. `--locked` is still always added, and an empty string skips the lane. A crate with mutually exclusive features needs `--exclude-no-default-features`: the powerset otherwise builds a combination the crate deliberately rejects with `compile_error!`, which is the guard working rather than a defect, and the invocation was previously hardcoded with no way for a caller to say so.

- `board-binaries` and `board-min-tests` on `rust-full`, and `binaries` / `min-tests` on the `board-run` action. `board-binaries` selects test binaries to run **directly, one process per binary**, given one per line as `<name-prefix>[=<filter>[,<filter>...]]` — a bare prefix runs the whole binary, filters run it once per filter as a libtest substring match. This is an alternative to `board-extra-args`, which routes the archive through nextest; callers that do not set `board-binaries` are unaffected. Use it for any board with a GPU. nextest runs one process per test, so each test pays a full driver init and teardown, and coverage instrumentation writes one profraw per process. Measured on an i.MX 8M Plus: 6 to 22 seconds per GL test and 307 profraw files totalling 2.8 GB, against 4.1 GB free, where whole-binary execution of the same selection is ~20 files and ~190 MB. Two behaviours come with it, both of which nextest's model cannot express: a non-zero exit is tolerated when the log shows a clean libtest summary with no failures, because the Vivante driver aborts while unloading its library after tests have passed; and `board-min-tests` fails the lane when fewer than that many tests ran, since a selection matching nothing otherwise reports success.

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
- `ruff-version` on `rust-quick` and `python-quick` pins the exact ruff `uvx`
  runs, e.g. `0.16.7`. Empty keeps today's behaviour. Both workflows called
  bare `uvx ruff`, and `setup-python-uv` enables the uv cache, so the version
  a lane linted with was whatever that runner's cache happened to hold -- not
  reproducible, and it drifts without any signal. hal hit the inverse case: a
  contributor's local ruff 0.15.8 reported five `F403`s on star re-exports
  that the CI-resolved 0.16.7 does not, so the mandatory local gate failed on
  a tree `main` passes. Callers that pin get one version across every repo;
  callers that do not are unaffected.
- `check_license_policy.py --self-test` covers the SPDX evaluator against the
  expressions that have broken the fleet. The shared CI lint job runs it.
- `rust-full` `board-pre-command`, `board-extra-args`, and `archive-args` so
  on-target jobs can skip host package installs, run tests with `-j 1`, and
  archive a different feature set than the host matrix. Host linux-arm
  uploads merged LFS testdata as `ci-testdata` for the board to download.

### Changed

- `rust-full`'s `nightly-extra` job no longer runs `cargo audit`; that moved to `advisories.yml` so it is not gated. The job is now named **Feature combinations**, which is all it still does, and it skips entirely when `hack-args` is empty rather than booting a runner to install tools and run nothing. Callers wanting advisory scanning must add the `advisories.yml` job, as `templates/nightly.yml` now does.

- `nightly-gate` now actually skips. Two things stopped it. It only applied its "has main moved" check on `schedule`, so a `workflow_dispatch` bypassed it silently and re-dispatching a nightly rebuilt the same commit, re-running the board -- the slowest and only hardware-bound lane -- for no new information. And it compared against the last **successful** run, which in a repository whose nightly is not consistently green means comparing against an arbitrarily old commit: hal's last green nightly on main was 2025-12-08, so the gate had not skipped once in nine months. The check now applies to every trigger and compares against the last **completed** run, of any conclusion.

  A new `force` input runs anyway. It is the only way to re-run an unchanged commit, which makes it the way to re-try after fixing a lane rather than the code. Callers that do not pass it get `false`. `templates/nightly.yml` forwards it as `${{ inputs.force || false }}` -- the fallback is required, because `inputs` is null on a schedule trigger.

- Runner policy is now per tier rather than a single cost-first ordering.
  Quick stays on free standard runners and never bills; Full and Release
  default to `larger`, which is what they were before this migration. Moving
  those lanes to standard runners to save money made hal's Full tier slower
  than the 15-to-20-job workflow it replaced, which is a failed migration, not
  a saving. The `larger` class maps to `ubuntu-24.04-xlarge` /
  `ubuntu-24.04-arm-xlarge` to match the hosted class.

### Fixed

- Board coverage merge failed with "not found object files" once a board lane completed far enough to produce profraw. An artifact round trip does not preserve the executable bit, and `cargo llvm-cov` collects object files by filtering on executability, so the downloaded instrumented binaries were invisible to it whatever directory they sat in. They are now made executable before the report runs, and a genuinely missing artifact reports itself rather than surfacing as llvm-cov’s opaque message.

- The license policy self-test asserted case folding only on the allowed side. A case-sensitive compare does not mis-sort a lower-case blocked identifier, it fails to recognise it, so the expression falls through to `unknown` and is rejected for the wrong reason — and both outcomes read as a failure, so an ok/fail assertion could not tell them apart. It now asserts the classification rank for blocked and review identifiers across casings.

- `board-run` passes `--workspace-remap`. A nextest archive records the
  workspace root it was built under, so one built on a hosted runner looked for
  its manifest at that path on the board and failed before running a test.
- `board-run` extracts the archive into the workspace with `--extract-to` and
  points `TMPDIR` there as well. nextest extracts to a temp directory by
  default, which on a board is a small RAM-backed `/tmp` tmpfs: it ran out of
  space while the workspace filesystem still had room. `df` is now reported for
  both filesystems.
- `rust-full` takes `archive-profile` so the on-target archive is built with a
  release-like profile. The archive was built on the default dev profile, so it
  carried full debug info for 26 instrumented binaries plus a standard library
  and exhausted the board's eMMC with `No space left on device`. The shipped
  nextest is stripped, and `board-run` clears the previous payload and reports
  headroom before unpacking, because its cleanup only runs after a job that
  succeeded and a failed one used to leave everything behind.
- `board-run` no longer tries to install nextest on the board. A Yocto board
  has neither `jq` nor `curl` nor a distro `install-action` recognises, so the
  install exited 127 and took the on-target lane with it. The aarch64 lane now
  ships a statically linked aarch64 `cargo-nextest` inside the archive artifact
  and the board executes it directly, since `cargo nextest` needs a cargo the
  board does not have. A nextest already on the runner still wins.
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
