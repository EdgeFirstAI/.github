# AI assistant guidelines (canonical)

This file is the organisation-wide process, CI and release guide for EdgeFirst and Maivin repositories. Product repositories keep a short stub that links here and then lists only project-specific layout, tests and hardware notes.

Source of truth: [EdgeFirstAI/.github/.github/copilot-instructions.md](https://github.com/EdgeFirstAI/.github/blob/main/.github/copilot-instructions.md) Design: [CICD Pipelines](https://au-zone.atlassian.net/wiki/spaces/EAM/pages/2750906369/CICD+Pipelines)

## Git workflow

- Every change starts from a JIRA ticket. Branch from `main`: `feature/EDGEAI-123-short-description`, `bugfix/EDGEAI-123-…`, `release/X.Y.Z` or `release/X.Y.Z-rcN` for a candidate. Nothing else after the three numeric fields; the tag workflow rejects it.
- Commits: `EDGEAI-123: Imperative summary` plus DCO (`git commit -s`).
- Land via pull request. Do not push to `main` or create `v*` tags by hand.
- Authors who are not organisation admins need one approving review (CODEOWNERS on owned paths). Organisation admins may merge their own PRs without a human approval and may rely on Copilot code review. `ci-gate` is still required for every merge, including admin merges.
- Open long-running work as **draft** PRs. Drafts run no CI. Mark ready when you want the Quick tier.

## CRITICAL: stay at the repository root

Do not `cd` into subdirectories. Cargo, cmake, uv and git all accept paths from the root; changing directory loses assistant context.

## Three CI tiers

| Tier | When | What |
| --- | --- | --- |
| **Quick** | every non-draft PR push | fmt, lint, check, host tests, dependency license policy (NOTICE required; C/C++ graphs wait for Full scancode). Target under 10 minutes (hal 15). |
| **Full** | `ci:full` or `ci:hardware` label, `workflow_dispatch`, or merge queue | platform matrix, boards, coverage, scancode. Once per PR, not once per push. |
| **Nightly** | schedule, only if `main` moved | Full plus slow suites. Quiet days cost nothing. |
| **Advisories** | every schedule, gated or not | `cargo audit`. See the exception below. |

Labels:

- `ci:full` — run the Full host matrix (and boards when configured).
- `ci:hardware` — run only the on-target lane and its aarch64 archive.
- Legacy `test-hardware` is replaced by `ci:hardware`.

Add `ci:full` before approving when the PR touches build/workflows, `unsafe`, FFI, GL/G2D/DMA, platform `cfg`, dependency versions or public API. Skip it for docs, comments and test-only refactors with green Quick. When in doubt, label.

Branch protection requires exactly one check: **`ci-gate`**. Path filters may skip Quick; the gate still runs and treats `skipped` as success.

## Runner selection policy

Two placements are fixed. Every other one is a judgement call, and this section exists to say which is which.

**Fixed: the Quick tier never bills, and `advisories.yml` never bills.** Quick runs on every push and the advisory scan is ungated, so neither has any bound on how often it would cost money. Nothing else in the pipeline is unbounded, which is why nothing else is fixed.

**The billed larger runners are available to the Full, Release and Nightly tiers. They are not required by any of them.** A release build on a free hosted runner is not a policy violation — it is the free class doing the job, at whatever speed it does it. Moving that lane to `larger` is not an upgrade to apply on sight either. It is a trade of money for wall-clock that a person makes, once, with the numbers in front of them:

- **what the lane actually takes on each class**, measured from its own run history. More cores are not proportionally faster for a link-bound step, a single fat crate, or anything serialised behind one `cc` invocation, and some organisation larger images are slower to start than the hosted ones.
- **how often it runs** — per push, per pull request, per release branch, or per night. Frequency, not duration, is what turns minutes into a bill.
- **what those minutes cost**, from the monthly snapshot `usage-report.yml` posts.

Write the answer down where the lane lives, so the next reader inherits a decision instead of re-deriving one. The tier below is the starting point for that conversation, not its conclusion.

| Tier | Optimise for | Starting point | Billed class available |
| --- | --- | --- | --- |
| **Quick** | cost **and** speed | `hosted` — free standard runners, always | no — fixed |
| **Full** | speed, cost accepted | `larger` | yes |
| **Release build** | speed, cost accepted | `larger` where the shared workflow compiles; `hosted` in the caller templates | yes |
| **Publish** | cost | `hosted` — it downloads and uploads; it never compiles | no use for one |
| **Nightly** | speed, cost bounded by the gate | `larger` (nothing blocks on it; see below) | yes |
| **Advisories** | cost, absolutely | `hosted`, hard-coded — see the exception below | no — fixed |

1. **hosted** — `ubuntu-24.04`, `ubuntu-24.04-arm`, `macos-latest`, `windows-latest`. Free and unmetered on public repositories. This is the Quick tier everywhere, with no exceptions: the per-push path never bills.
2. **larger** — `ubuntu-24.04-xlarge`, `ubuntu-24.04-arm-xlarge`, `macos-latest-xlarge`, `windows-latest-8-cores`, via `runner-class-*: larger`. Offered to Full and Release, and the default the shared workflows ship for the lanes that compile. What makes it affordable at all is that those tiers run once per PR or per release branch rather than once per push, so the spend is bounded by review cadence rather than by typing — and that bound is the argument for being *allowed* to pay, not an argument for paying. The organisation's direction is the other way: hosted first for anything that fits, the fleet for what does not, and billed minutes trending to zero. A Full tier that is slower than the pipeline it replaced is a failed migration, not a saving; a Full tier that is fast enough on the free class and billed anyway is the same failure with the sign flipped.
3. **fleet** — self-hosted groups `boards`, `build-x86`, `gpu-cuda`, `mac`, `windows`, `yocto`. Full and Nightly only. Trusted triggers are `push`, `workflow_dispatch`, `schedule`, `merge_group` and same-repository `pull_request`; anything else is untrusted and forced to `hosted`. Phase 2 moves the Linux, Windows and CUDA lanes here and retires those larger runners; macOS stays billed because a hosted Apple runner has no free equivalent.

**Capability is a separate axis from cost.** `runner-class-*` answers "who pays"; `lanes` answers "what must the machine have". `lanes` is a comma-separated set of `host`, `hardware` and `gpu`. `all` means `host,hardware` and never implies `gpu` — the CUDA lane is opt-in, needs `gpu-args` to be non-empty, and runs on `self-hosted,Linux,X64,CUDA`. There is no `runner-class-gpu`: a CUDA lane is self-hosted by definition. Like the board lane, it is disabled for any trigger that is not positively trusted — `push`, `workflow_dispatch`, `schedule` and `merge_group`, plus same-repository `pull_request`. Anything else, including `pull_request_target` and `workflow_run`, is treated as untrusted and downgraded to hosted runners.

Yocto builds are not Rust builds and do not belong in `rust-full.yml`. They call `yocto-build.yml`, which refuses any untrusted trigger outright rather than downgrading — there is no hosted Yocto runner to downgrade to.

Putting a Quick lane on a billed runner is the defect the nightly audit exists to catch, and it is the only placement that is wrong by construction. A Full, Release or Nightly lane on a billed runner is permitted rather than expected: when such a lane names the label directly rather than going through `runner-class-*`, put `# runner-class: larger` in the file, with the measurement that justified it, so the audit can tell a priced decision from an unexamined one. A lane on a free runner needs no marker and no defence — it is the cheaper half of a trade someone already considered.

### The one exception: advisory scanning

`advisories.yml` breaks both rules above on purpose, and the reasons are
narrow enough that nothing else should copy it.

**It is not gated.** Every other Nightly lane asks a question about the code,
so skipping an unchanged commit loses nothing. `cargo audit` asks a question
about the RustSec database, which changes daily whether the code does or not.
Gated, it goes quiet exactly when a new advisory lands against a frozen
`main` -- which is not hypothetical: the 2026-09-15 nightly failed on
RUSTSEC-2026-0204 against a `Cargo.lock` nobody had touched.

**It is `hosted`, not `larger`, and hard-codes the label** rather than
honouring the caller's `runner-class-*`. "Cost accepted" is affordable for
Nightly because the gate bounds it to days when `main` moved. An ungated lane
has no such bound, so it only stays affordable on a free class. Hard-coding
means a caller cannot put an every-night lane on a billed runner by setting
`runner-class-linux: larger` for unrelated reasons.

The exception is affordable only because the job is trivial: `cargo audit`
parses `Cargo.lock` and never compiles, so it skips `setup-rust` and is
seconds of a free runner. A lane that builds anything does not qualify --
gate it, or leave it out of the nightly.

`runner-audit` does not flag `advisories.yml`, because `ubuntu-24.04` is not a
billed label; it needs no `# runner-class: larger` marker.

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

The `uses:` pin is the only place the shared commit appears. The shared workflows reach their own composite actions with GitHub's self-repository syntax — `uses: $/.github/actions/…`, which resolves to the running workflow's repository at the commit already running — so there is no second SHA to keep in sync and Dependabot's bump is complete on its own. It requires an Actions runner of 2.336.0 or newer. `$/` is for the shared workflows themselves; a product repository still writes the full `EdgeFirstAI/.github/…@<sha>` form and still pins it.

Copy the caller skeletons from [`templates/`](https://github.com/EdgeFirstAI/.github/tree/main/templates). Repository-specific steps (ANGLE, LFS testdata, OpenCV, `vcan0`) become **inputs**, not pasted jobs. `templates/` also carries `CODEOWNERS` and `dependabot.yml`: a migrated repository requests review automatically on every pull request, and keeps its dependencies current itself.

**Migrate the workflows in their own pull request, before any release PR.** GitHub will not dispatch a workflow that is not on the default branch, and merging a release PR fires `tag-release.yml` immediately — so a repository that introduces `publish.yml` *in* its release PR can never run the rehearsal that Section 4.5.6 requires: the file is absent from `main` until the merge, and the merge creates the tag. Land the five callers as an ordinary PR, then prepare the release on top.

**Bring dependencies current before preparing a release, not after.** A release cut on stale dependencies is behind the moment it ships, and adopting `dependabot.yml` in the same change opens a wave of PRs immediately after the tag — which is what ara2-rs did, with five `build(deps)` PRs arriving while v0.18.0 was still publishing.

Inputs that matter:

- `rust-quick`: `python` (ruff lint), `python-tests` (adds maturin develop + pytest), `ruff-paths`, `ruff-version` (exact ruff for uvx; empty takes whatever the runner's uv cache holds), `timeout-minutes` (hal: 15), `cross-targets`, `runner`, `clippy-args`, `clippy-extra-args` (optional second host pass), `cross-clippy-args` (narrow the per-target pass rather than disabling it with `skip-cross-clippy`), `workflow-lint` (actionlint + SHA-pin policy, on by default), `clippy-report` (emit and upload a machine-readable clippy report as `clippy-report-<os>`, for a SonarCloud project that imports one rather than letting Sonar recompile the workspace), `env` (KEY=VALUE lines), `pre-command` (caller setup after checkout). The cross-clippy pass installs the cross C toolchain for its `cross-targets`, so a workspace with a build-script dependency no longer has to disable the lane
- `rust-full`: `lanes` (comma-separated set of `host`, `hardware`, `gpu`; `all` means `host,hardware`), `boards`, `nightly`, `runner-class-linux` / `-linux-arm` / `-macos` / `-windows`, `gpu-args` (opt into the CUDA lane; non-empty is what enables it), `gpu-pre-command` (GPU job setup; falls back to `pre-command`), `env` (KEY=VALUE lines, every lane), `pre-command` (host jobs), `board-pre-command` (board; falls back to `pre-command`), `board-extra-args` (`-j 1` and similar; not used for archive), `archive-args` (nextest archive features/packages; empty uses `nextest-args`). The SonarCloud job is skipped automatically when the repository has no `sonar-project.properties`.
- `sbom`: `mode` `dependency` \| `full`
- `release-rust` (release-branch side): `sbom`, `sbom-targets`, `sbom-extra-manifests`, `changelog`, `project-name`, `package-crates`, `crate-packages` (package names in dependency order), `package-runner`, `package-env` and `package-pre-command` (the packaging job compiles, so a crate whose build scripts need an OpenCV root or a sysroot configures it here). It verifies, scans, and runs `cargo package` — which compiles, so that job defaults to the `larger` class and `package-runner` moves it to a free one when the measured time says the billed class is not buying anything. It builds no distribution artifact beyond the `.crate` files; wheels are `release-wheels`, and anything else stays in the product repository — see the release chain below
- `release-wheels` (release-branch side): `manifest` **or** `builds` (JSON array of `{manifest, features, args}` for a workspace shipping several bindings, looped inside one job; a `runners` entry may carry its own to vary it per platform), `runners` (JSON matrix; defaults to the `larger` class because a wheel build compiles, and a caller naming the hosted labels instead is making the cost trade deliberately rather than breaking a rule — an entry may also override `builds` or `maturin-spec` for that lane alone), `python-version`, `maturin-spec`, `features`, `lfs`, `artifact-prefix`, `payloads` (JSON array of artifact names from this run, downloaded into `payload/<name>/` for a wheel whose native content is built by a sibling job), `wheel-data` (JSON array of `{from, scheme, path, mode, wheel}` placing those files into the built wheel's `.data/` directory, for either binding mode), `env`, `pre-command`, `post-command` (assertions over the built wheels, before the upload), `verify-version`, `attest` (on by default — the calling job must grant `id-token: write` and `attestations: write`, **and `actions: read`**, which the shared job now declares unconditionally)

The body of that workflow is the `maturin-build` composite action: install the right maturin, build each entry, verify the wheel versions against the release branch, attest. A repository whose matrix does not fit `release-wheels.yml` calls the action directly from its own job rather than re-implementing the build. The rule of thumb: a reusable workflow owns whole jobs, so it fits a repository that wants the standard shape and configures it, while an action composes into a job that already exists and fits one that needs its own steps interleaved with the build. `maturin-build` neither checks out nor uploads; both stay with the caller.

`maturin-spec` is derived from the runner OS when unset — `zig` produces the manylinux wheels and `patchelf` has no wheel for macOS or Windows — so set it only to pin a maturin version.

- `publish-rust` (tag side): `tag` (rehearsal), `build-workflow`, `publish-crates`, `crate-packages` (dependency order; the list `release-rust` recorded is authoritative and a different value here fails the publish), `changelog`, `require-sbom`, `release-files`, `dry-run`
- `publish-container` (tag side, for a repository shipping an image): `tag` (rehearsal), `build-workflow`, `digest-artifact`, `registry` (empty uses the one the build recorded), `aliases` (moving tags, final releases only), `mirror` and `mirror-images`. It builds nothing: the release branch pushes candidates and records an immutable digest per image with the `record-image-digests` action, and this promotes exactly those digests, asserting afterwards that promotion did not change one. There is deliberately no `release-container.yml` — the builds have nothing in common, so `templates/release-container.yml` is the caller skeleton and the digest manifest is the shared contract. Promotion stops at the registry; registering Batch job definitions or Studio app versions is deployment, and must use the `digests` output rather than a tag

**Registry authentication is organisational, not per repository.** A project names *where* it publishes and the `registry-login` action derives *how* from the hostname: `ghcr.io` takes the job's own token, a `*.dkr.ecr.*.amazonaws.com` registry takes OIDC via the organisation variable `AWS_ECR_ROLE_ARN`, and `docker.io` takes the organisation's `DOCKERHUB_*` secrets. An unrecognised registry fails with the supported list rather than falling back. ECR needs `id-token: write` at the call site, and the container jobs declare it unconditionally, so a caller must grant it even when publishing only to GHCR.

Every lane reaches its toolchain through the `setup-rust` action, which also
guarantees the things a lane assumes rather than checks: a committed
`Cargo.lock` (`require-lockfile`), the channel from `rust-toolchain.toml`, and
a C compiler (`require-cc`). The organisation's larger-runner images are not
the GitHub-hosted images and do not all carry one — Rust links through `cc`,
so without it every build script fails before a test runs.

### The `pre-command` hook

Repository setup that cannot be expressed as an input (install OpenCV, fetch ANGLE, merge LFS testdata) goes in a script in the calling repository, named by `pre-command`. It runs after both checkouts and before the toolchain setup.

The command string is passed to the step through `env` and executed with `bash --noprofile --norc -euo pipefail -c "$PRE_COMMAND"`. It is never interpolated into the script text, so a caller cannot inject steps.

What a pre-command may rely on:

- the caller's checkout as the working directory;
- `GH_TOKEN` and `GITHUB_TOKEN`, set to the job's `github.token`, for `gh` and API calls such as release-asset downloads;
- `GITHUB_ENV` and `GITHUB_PATH` to export state to later steps.

Nothing else is guaranteed. Secrets are **not** passed to the hook; a step that needs one belongs in the calling repository's own workflow.

The hook runs code from the pull request's head, so on a fork PR it is attacker-controlled. That is the same exposure as `build.rs` or any test, and it is why `rust-full` forces hosted runners and disables board lanes for fork PRs. Never add a self-hosted lane that skips that guard.

Every job in the shared workflows has `timeout-minutes`. Every third-party action is SHA-pinned. Do not reintroduce unpinned tags or jobs without a timeout.

## Release chain

Three workflows, one action each. **A tag deploys; it never builds.**

| File | Trigger | Action |
| --- | --- | --- |
| `release.yml` | push to `release/*.*.*` | **build** every distribution artifact; publish nothing |
| `tag-release.yml` | `release/*.*.*` PR merged to `main` | **tag**: annotated `vX.Y.Z` at the merge commit |
| `publish.yml` | push of a `v*.*.*` tag | **publish** what was already built; build nothing |

1. Branch `release/X.Y.Z` (or `release/X.Y.Z-rcN`), bump versions and CHANGELOG, open a PR to `main`. Label `ci:full`.
2. Every push to that branch runs `release.yml`: the shared `release-rust.yml` checks version consistency — including each `[workspace.dependencies]` entry carrying both `path` and `version`, so a workspace cannot half-bump and publish a member depending on its sibling's previous release — checks the changelog section, produces the SBOM, and runs `cargo package`, recording the package list beside the `.crate` files it produced. `release-wheels.yml` builds the wheels where the repository ships a PyO3 binding. Anything else — C API archives, container images, binaries — stays in the repository's own build jobs and uploads with `retention-days: 30` or more.
3. Merge the PR. The shared `tag-release.yml` creates an **annotated** `vX.Y.Z` tag at the merge commit using `RELEASE_TAG_TOKEN`, after checking that `release.yml` is green for the release-branch head being merged (`require-build`). Leave `require-build` empty only in a repository whose release still builds on the tag.
4. The tag starts `publish.yml`, which calls `publish-rust.yml`: it finds the successful `release.yml` run for the matching release branch, verifies that run's tree SHA equals the tag's, downloads the artifacts, publishes crates via OIDC (environment `crates-io`), and creates the GitHub Release from the CHANGELOG. Pre-release tags are marked as such and never become `latest`; maintenance tags never displace semver `latest`.

**Release candidates and the registries.** crates.io and PyPI versions are immutable, so a candidate may upload to them only when the manifest version is exactly the tag version. `release/1.2.0-rc1` whose manifests still say `1.2.0` gets a GitHub pre-release with every artifact attached and **no** registry upload — publishing `1.2.0` from the candidate would permanently consume the version the final release needs. Give the manifests the pre-release spelling (`1.2.0-rc.1` for cargo, `1.2.0rc1` for PEP 440) when the candidate is meant to be installable from a registry. The rule is mechanical and needs no input: exact match publishes, base version does not.
5. **Never tag by hand.** The one exception is a maintenance line cut from an older tag (`release/X.Y.Z` not merged to `main`); maintainers may create that tag through the OrganizationAdmin tag-ruleset bypass (`RELEASE_TAG_TOKEN` must be a token owned by an org admin). The artifacts still come from a `release.yml` run on that branch.

### Why the build is not on the tag

A tag-triggered workflow cannot be run by a pull request, so anything it builds is built at the one point in the process where nothing can test it, and its failures are only ever found after the tag exists. Measured on hal before this split: five of nine release tags failed, and **every one of those was a build failure at deploy time, never a publishing failure**. v0.32.0 failed three times in a row and each retry required deleting and re-pushing a tag that `protect-release-tags` exists to make immutable.

The release PR is where a build failure now surfaces, hours before a tag is involved. Be precise about what enforces it: branch protection requires `ci-gate` only, and the release build runs on a branch push rather than on the pull request, so a red build does not block the merge button. What it blocks is the **tag** — `tag-release.yml` with `require-build: release.yml` refuses to create one unless the build is green for the release-branch head being merged — the PR's head SHA, which is the commit the build actually ran on, not the new commit a squash merge creates. A merged PR with a broken build therefore leaves no tag, rather than a tag whose artifacts do not exist.

### The build itself stays in the product repository

`release-rust.yml` deliberately does not build. The build is the one genuinely repository-specific part of a release — hal ships five wheels across eight targets plus ten C-API archives with codesigning, schemas ships ten wheels, videostream ships C — and a shared matrix guessing at that shipped in 1.0.0 and never ran anywhere. What is shared is everything around it: version consistency, the changelog contract, the SBOM, and the entire publish side.

Two rules make a repository's build work with `publish-rust.yml`:

- `retention-days: 30` or more on every artifact the release ships. The release-PR-to-tag gap is human-paced, and publish fails on an expired artifact rather than rebuilding.
- `if-no-files-found: error` on every upload. A silently empty artifact is a silently incomplete release.

### Rehearse before the first tag

`publish.yml` carries a `workflow_dispatch` with a tag input, and its publishing steps are gated inside the shared workflow on a real tag push. A dispatch therefore resolves the build, verifies the tree binding, downloads every artifact, collects the wheel set, renders the release notes and publishes nothing. The tag does not need to exist — rehearsing *before* the tag is the entire point — so a dispatch binds the build to the release branch head instead of to the tag. It is free, it is the only pre-tag test the publish path has, and it is a **required** step of every repository's migration.

### PyPI and crates.io trusted publishing

Both match on workflow **filename**. Splitting the chain moves publishing from `release.yml` to `publish.yml`, so **every publisher configuration must be re-pointed before the first tag** or the upload fails on a claim mismatch. The rehearsal will not catch it, because a rehearsal skips the upload. Re-point first, dispatch second, tag third.

PyPI matches `job_workflow_ref` in the **publisher repository**, so a reusable workflow in `EdgeFirstAI/.github` cannot be a Trusted Publisher ([docs](https://docs.pypi.org/trusted-publishers/troubleshooting/)). `publish-rust.yml` stages the artifacts into the caller's run under the name `release-artifacts`, and each repo's `publish.yml` keeps a small `publish-pypi` job with environment `pypi`. Composite actions are fine inside that job — only reusable workflows change the claim — so the selection and verification are the shared `stage-pypi` action (`publish-pypi` is its deprecated predecessor and cannot upload). The upload is not shareable: `pypa/gh-action-pypi-publish` resolves its own container image from the repository it is called from, so nesting it in one of our actions resolves it to `EdgeFirstAI/.github` and fails on an image that does not exist. It goes directly in the job.

That action selects by **filename**, not by artifact name: a wheel filename already carries the distribution and the version canonically, so nothing has to agree in advance about how a build names its artifacts. Call it once per distribution, which a repository shipping several needs anyway since each has its own environment. Naming the distribution also makes its sdist safe to take — an unscoped `*.tar.gz` matches a C API archive, and PyPI rejects it after the crates have already published. crates.io **does** work from the shared workflow (caller `workflow_ref`).

## License policy (zero tolerance)

Pre-approved: MIT, Apache-2.0, BSD-2/3-Clause, ISC, Unlicense, CC0-1.0, MPL-2.0 and the additional SPDX ids in `.github/scripts/check_license_policy.py`. LGPL is forbidden in Rust (static linking). GPL/AGPL/SSPL are blocked. NXP proprietary is allowed only when documented in NOTICE. Do not wrap license checks in `|| true` or `continue-on-error`.

Use the shared `sbom-tools` action; do not keep a private copy of `generate_sbom.sh` / `check_license_policy.py` / `validate_notice.py`.

## Code quality and security

- `cargo fmt --check`, clippy `-D warnings`, `--locked` everywhere.
- No secrets in the tree. Hash-pin GitHub Actions.
- CHANGELOG follows Keep a Changelog. Version files must match at release.

## Housekeeping

- PRs stay reviewable; prefer small diffs.
- Signed-off-by on every commit.
- Public API changes need a CHANGELOG entry in the same PR.
