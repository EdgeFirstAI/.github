# Changelog

All notable changes to the EdgeFirstAI shared CI workflows are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`publish-rust.yml`'s `cargo publish` step now issues one multi-package invocation for a dry-run rehearsal, instead of looping per package.** For a workspace with an inter-dependency — `ara2` depending on `ara2-sys = "^X.Y.Z"` — the loop's second `cargo publish -p ara2 --dry-run` could never resolve: a dry run never actually uploads `ara2-sys`, so by the time the loop reached `ara2` the crates.io index still had no `X.Y.Z` to satisfy the requirement, and the rehearsal failed with `failed to select a version for the requirement`. This was not specific to `ara2-rs`'s tree; it fails identically for any inter-dependent workspace, on every rehearsal, regardless of what changed. `cargo publish -p foo -p bar` (stable since cargo 1.90) resolves every named package against the workspace graph in one pass, so the dependency is satisfied locally instead of through the registry.

  The fix is scoped to the rehearsal path only. A real (non-rehearsal) publish keeps the per-package loop unchanged — each package genuinely lands on the index before the next needs it, so it needs no particular cargo version — and the rehearsal path checks the runner's cargo version itself before relying on 1.90's multi-package support, failing with an explicit message rather than cargo's own argument-parsing error on an older toolchain.

## [2.0.0] - 2026-09-22

**Upgrading.** Nothing to do. `publish-pypi` is removed, and no repository referenced it: `hal`, `ara2-rs`, `client`, `videostream`, `tflite-rs` and `schemas` each call `pypa/gh-action-pypi-publish` directly from their own job, which is the supported usage and is untouched here. The major bump records that a published action was withdrawn, not that anything has to change.

### Removed

- **`publish-pypi`. It could not upload, and never did.** It was introduced in 1.2.0; profiler was its only consumer, adopted it in the tiered migration, and v1.17.0 was the first tag to reach it. It failed there, after the images had been promoted and the archives uploaded, leaving the wheels unpublished and the GitHub release a draft.

  `pypa/gh-action-pypi-publish` resolves its own container image from the repository it is called from, and identifies itself by numeric repository ID. Called through an action of ours it sees `EdgeFirstAI/.github` instead, takes its "this is a fork, pull its prebuilt image" path, and runs `docker run ghcr.io/EdgeFirstAI/.github:<sha>` — an image that is rejected as a reference, because a repository name must be lowercase, and does not exist in any case. No input fixes it, and no pin does either: v1.14.2, which `hal` and `ara2-rs` already use, resolves the image the same way. The upload has to be a direct step of the calling job.

  It is removed rather than deprecated because there is nothing to keep working. A deprecated copy would have been a broken action retained for no caller.

### Added

- **`stage-pypi`, which selects one distribution's files into `dist/` and asserts their version.** It is `publish-pypi` without the upload, and it is what was actually shareable: the selection is by wheel filename, so nothing has to agree in advance about how a build names its artifacts. The caller runs `pypa/gh-action-pypi-publish` as a direct step of its own job.

  `templates/publish.yml` keeps its `publish-pypi` **job** — the job name is unchanged and Trusted Publishing still requires it to live in the product repository — and carries the two-step shape.

  Its first consumers are `profiler`, which stages the wheels before attaching them to the profiler-cli release, and `profiler-cli`, which stages them again before uploading.

## [1.2.2] - 2026-09-21

### Changed

- **`protect-main` and `protect-main-ci` target the organisation custom property `ci_tier` rather than a list of repository names.** A repository is covered once it is set to `ci_tier=tiered`, which is a setting on that repository; onboarding no longer means editing a central file here and re-applying. The list had already drifted — a repository could carry a green `ci-gate` for hours while the file that decides whether to enforce it knew nothing about that, because the question "does this repository have a ci-gate check" is a fact about the repository and was being tracked somewhere that cannot observe it. `protect-release-tags` is unchanged and stays `~ALL`.

  Coverage is unchanged by the conversion: `.github`, `ci-foundation-scratch` and `hal` were set to `tiered` before the rulesets were re-applied, and each still reports the same four rulesets it did before. The ordering matters — a ruleset whose condition matches nothing silently protects nothing.

  Setting the property on a repository that has no `ci-gate` check makes its main branch require a check that can never report. Nothing enforces that ordering.

## [1.2.1] - 2026-09-21

### Changed

- **`WTFPL` added to the license policy's allowed list.** It is public-domain-equivalent and grants strictly more than MIT, Unlicense and CC0-1.0, each of which the policy already allows, so admitting it narrows nothing.

  It surfaced on profiler through `ratatui` → `ratatui-termwiz` → `termwiz` → `terminfo`. No default feature set compiles that path — `cargo tree -i terminfo` finds nothing — but `cargo cyclonedx` reports the resolved `cargo metadata` graph including optional dependencies that are not enabled, so the crate reaches the SBOM without reaching any binary. Every repository whose graph contains a WTFPL crate, compiled or not, failed the policy until now.

  Policy version moves to 2.1. The marker records which policy an SBOM was judged against, and leaving it at 2.0 would let one version name two different allowed lists.

## [1.2.0] - 2026-09-20

**Upgrading.** Two permissions are now declared by shared jobs and must be granted at the call site, because a reusable workflow can only narrow what its caller holds — a job that omits one fails to start rather than degrading. A `release-wheels.yml` caller adds `actions: read`; a `publish-container.yml` caller adds `id-token: write`, including one publishing only to GHCR. `templates/release.yml` and `templates/publish-container.yml` carry both. The `$/` syntax below also requires an Actions runner of 2.336.0 or newer.

### Added

- **`check_action_outputs.py`, run by `workflow-lint`, which asserts that every composite action output a caller reads is declared.** A composite action's inner `$GITHUB_OUTPUT` writes are scoped to the action; at the call site `steps.<id>.outputs.<key>` resolves against the action's own `outputs:` block. A key missing from that block is not an error — it is the empty string, so a guarded lane stops running and the workflow still reports success. `actionlint` does not resolve local composite outputs, so nothing else in the lint chain sees it. Both `$/` and `./` spellings are checked; a reference to another repository is skipped, since its definition is not present to check against.

- **`clippy-report` on `rust-quick.yml`**, for a repository whose SonarCloud project imports a clippy report rather than letting Sonar compile the workspace itself. The self-compile is slower and less accurate: Sonar's runner carries none of a repository's build dependencies, so a crate with a build script fails to analyse while the scan still reports clean — measured on profiler at 171s of a 213s scan, with one crate silently unlinted.

  It could not be done through `clippy-args`. Adding `--message-format=json` there suppresses the rendered diagnostic, uploads nothing, and puts cargo's exit status behind a pipe, so a clippy failure reports success. The three clippy passes now share one implementation that renders diagnostics back, appends to a single report and sets `pipefail`.

- **`payloads` on `release-wheels.yml`**, for a wheel whose native content is built by another job in the same run — a CLI binary, a vendor shim. Named artifacts are downloaded into `payload/<name>/` before `pre-command`, and a missing or empty one fails the lane rather than shipping a wheel that installs and then fails at first use on a version PyPI will not let you replace.

  The job gains `actions: read`. Without it the existing `pre-command` and `post-command` hooks could not reach a sibling artifact at all, and a caller cannot add a permission to a reusable workflow's job — so this class of repository had no route into the shared wheel build whatever it wrote. The corollary is the upgrade note above: the permission is declared unconditionally, and a caller that does not also grant it at the call site fails to start.

- **`wheel-data` on `release-wheels.yml`, and the `wheel-data` action behind it**, placing files into a built wheel's `.data/` directory declaratively — `[{"from": "payload/*/*.so", "scheme": "data", "path": "lib"}]` in place of a 35-line unpack/copy/repack. It is the counterpart to `payloads`: that input gets a sibling job's artifact onto the disk, this one gets it into the wheel.

  It exists because the obvious mechanism only covers half the fleet. maturin folds a `<module>.data/` directory staged before the build into the wheel, but only for a binding that produces a Python module — `client` uses exactly that. A `bindings = "bin"` wheel has no such directory, so `profiler` unpacks and repacks the finished wheel instead. Unpacking serves both, and a caller no longer has to know which case it is in.

  `mode` is not cosmetic. The Actions artifact store does not preserve the executable bit, so a console script staged from a sibling job arrives 0644 and the wheel fails at first use, on a version PyPI will not let you replace. A `from` glob matching nothing fails the lane for the same reason `payloads` fails on an empty artifact.

  It runs after the build and **before** `post-command`, and the position is forced from both sides: `wheel pack` recomputes `RECORD`, so attesting first would publish provenance for a wheel nobody can install, and injecting after the caller's assertions would change a wheel those assertions have already described. `stage_wheel_data.py` carries a `--self-test`, which `ci.yml` runs.

- **`registry-login`, deriving container registry authentication from the registry's hostname.** A project decides where it publishes; the organisation decides how we authenticate there. `ghcr.io` takes the job's own token, a `*.dkr.ecr.*.amazonaws.com` registry takes OIDC through the organisation variable `AWS_ECR_ROLE_ARN`, and `docker.io` takes the organisation's `DOCKERHUB_*` secrets. An unrecognised registry fails with the supported list rather than falling back to a credential that cannot work.

  There is no override input. The hostname is unambiguous, and a fourth class should be a reviewed change here rather than a per-repository guess. Credentials appear in the action's signature only because neither `vars` nor `secrets` is readable inside a composite action, so the calling workflow resolves both; a caller does not choose them.

  `publish-container.yml` uses it at **both** ends. Only the source was authenticated before, and only as GHCR — so mirroring to a private ECR, the case the feature was built for, could not work, and neither could a repository whose release build pushes candidates to ECR in the first place, which is what the converters' `app_create.py` does today.

- **`publish-container.yml` and the `record-image-digests` action**, completing the release chain for a repository that ships a container image rather than a wheel or a crate. The build records an immutable digest per image; the tag promotes exactly those digests with `imagetools create` and asserts afterwards that the digest did not change, because a promotion that changes a digest means something rebuilt.

  There is deliberately no `release-container.yml` reusable workflow. The builds have nothing in common — one repository runs `docker build .`, another builds six variants across two architectures staging three vendor runtimes onto binaries from a sibling job — so a workflow spanning both would need a hook per caller. `templates/release-container.yml` is the caller skeleton instead, and the shared contract is the digest manifest. Promotion stops at the registry: registering Batch job definitions and Studio app versions is deployment, not release, so the workflow hands the caller an immutable reference and goes no further.

- **`allows_public_repositories` is declared per group and reconciled.** The documentation asserted this flag was `true` throughout while nothing verified it, so a group toggled to `false` would strand every public consuming repository — which is all of them — with `--dry-run` still reporting zero operations. It is now read and written alongside `visibility`, and the two share a single PATCH: sending a partial body would rely on undocumented leave-unchanged behaviour for whichever field was omitted.

- **`publish-pypi`, a composite action for the one job that cannot be a reusable workflow.** PyPI Trusted Publishing matches `job_workflow_ref` in the publishing repository, so the job has to live in the product repository — but only a reusable *workflow* breaks that claim, and an action inside the job does not. The selection and verification are shareable even though the job is not, and a caller writes four lines instead of a download, a `find`, an emptiness check and an upload.

  It selects by **filename** rather than by artifact name. A wheel filename already carries the distribution and the version canonically, so nothing has to agree in advance about how a build names its artifacts — the coupling that otherwise has to be maintained between every build and every publish, and the reason one-artifact-per-lane naming was awkward for a repository shipping several distributions. Naming the distribution also makes its sdist safe to take: the previous template took wheels only and said so, because an unscoped `*.tar.gz` also matches a C API archive and PyPI rejects it after the crates have already published. Scoped to `edgefirst_tracker-*` it cannot match `edgefirst-hal-0.32.0-x86_64-linux.tar.gz`.

  Downloading, selecting and verifying run during a rehearsal; only the upload is gated. A rehearsal whose job skips its own checks proves nothing about the files, which is the failure it exists to catch. `skip-existing` is on by default, because a release shipping several distributions can fail part way through and the retry must not fail on the ones that already landed.

- **`maturin-build`, a composite action holding the body of the wheel build**, and `release-wheels.yml` rebuilt on top of it with its inputs unchanged. Nearly every repository in the fleet ships a maturin wheel — `hal`, `client`, `profiler`, `schemas`, `tflite-rs`, `ara2-rs` — so the shape it is shared in decides whether they can all use it.

  A reusable workflow owns whole *jobs*, and that boundary has now been hit three separate times: `publish-rust.yml`, which hal could not use at all and which gave up its resolve step to a composite action; the `builds` input, because one call per binding is one job per binding and hal's five distributions across two abi3 passes would have been forty jobs instead of four, none of them sharing a `target/` directory or a warm cargo cache; and provenance, which needs a step after the build and which a workflow has no way to offer. The growing hook list — `pre-command`, `post-command`, `env`, and per-matrix overrides for `builds` and `maturin-spec` — is the same signal: every one exists because a caller needed to interleave its own work, which is what an action does natively and a workflow can only simulate.

  So the unit of work is an action: install the right maturin, build each entry, verify the wheel versions against the release branch, attest. `release-wheels.yml` is that action plus the standard matrix, the checkouts and the upload, and stays the answer for a repository shipping one binding on the usual platforms — its inputs do not change. A repository whose matrix does not fit calls the action from its own job and keeps its own steps around it, rather than re-implementing the build.

- **Build provenance for wheels, on by default**, generated in the job that built them. Provenance generated where an artifact was downloaded describes the download; generated where it was built it describes the build that produced what consumers install. The calling job must grant `id-token: write` and `attestations: write`, which `templates/release.yml` now does — an existing caller that does not will fail the attestation step until it adds them, and `attest: false` opts out for a repository that deliberately ships wheels no consumer can verify.

- **Default community health files: `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md` and `SUPPORT.md`.** The organisation published none, so a repository without its own had no code of conduct, no security reporting route and no contributing guide — and these, unlike CODEOWNERS, *are* inherited by repositories that lack them. `CONTRIBUTING.md`, `SECURITY.md` and `SUPPORT.md` are defaults a repository may replace; the code of conduct is not. It is the organisation's policy and applies everywhere, and a repository carrying a copy is carrying a copy rather than a variation. Adapted from hal's, which were the most developed set, with everything repository-specific removed: an inherited file is served verbatim in the consuming repository's context, so a link to one repository's security tab or a version-support table for one project would be wrong everywhere else. Cross-references between the four are absolute URLs into this repository for the same reason — a relative link would resolve against a repository that does not have the file.

  `CONTRIBUTING.md` keeps what is genuinely common — branch and commit conventions, DCO, the pull request flow, the three CI tiers and the release chain — and says that build commands, toolchains and test layout belong in each repository's own copy, which supersedes this one. hal's 499-line guide stays hal's.

- **`templates/publish-container.yml`**, the caller skeleton for the tag side of the container chain, alongside the `release-container.yml` added with it. Its `register` job is the worked example of consuming the `digests` output rather than composing a tag reference, which is the correctness point the whole chain turns on.

- **`templates/CODEOWNERS` and `templates/dependabot.yml`.** A migrated repository should request review automatically on every pull request and keep its own dependencies current; neither was inherited from the templates, so both were left to each repository to remember. The CODEOWNERS template carries a catch-all, and states the two GitHub rules that are easy to get backwards: the last matching pattern wins rather than the most specific one, so the catch-all goes first; and CODEOWNERS is not a default community health file, so ownership does not cross repository boundaries and every repository needs its own copy. This repository's own file claimed otherwise and is corrected.

- **An opt-in CUDA lane, on its own axis.** `lanes` becomes a comma-separated set — `host`, `hardware`, `gpu` — where `all` keeps its exact prior meaning of `host,hardware` and never implies `gpu`. That restraint is the point: every migrated repository passes `all`, and two GPU machines cannot absorb the whole fleet's Full tier. The lane needs a non-empty `gpu-args` and runs on `self-hosted,Linux,X64,CUDA` with no `runner-class-gpu` input, because a CUDA lane is self-hosted by definition and a class input could only name a runner that does not exist. It inherits the board lane's fork guard. `lfs: true` on this lane requires `git-lfs` preinstalled on the CUDA hosts; the lane fails with that remedy rather than installing it, since the CI user has no passwordless sudo there.

  Capability and cost are now separate axes. `runner-class-*` answers who pays; `lanes` and `boards` answer what the machine must have. Folding CUDA into the class enum would have multiplied every future capability against every OS, and would have let a caller write `runner-class-macos: fleet-cuda` that type-checks and queues forever.

- **`yocto-build.yml`**, for bitbake on the dedicated builder. It is a separate workflow rather than a lane because `rust-full.yml` runs cargo and a Yocto build shares nothing with it. It refuses any untrusted trigger outright instead of downgrading — the Rust lanes can fall back to hosted runners, and there is no hosted Yocto equivalent to fall back to — serialises builds of the same MACHINE target within a repository (one-runner-per-device policy is what keeps the physical box itself to one job at a time), and prunes `tmp/` on completion while leaving `DL_DIR` and `SSTATE_DIR` outside the workspace where the runner cannot delete them.

- **`.github/rulesets/runners.json` and `apply-runners.sh`**, making organisation runner state declarative. Groups, repository access lists and custom labels were applied by hand from a markdown table, and the organisation had drifted from that table completely: six of seven self-hosted runners sat in `Default`, five purpose-built groups were empty, and a sixth group existed that the table did not mention. State that is reviewed in a pull request does not drift that way.

### Changed

- **The runner selection policy states that billed runners are available, not required.** The tier table read as a mandate — Full, Release and Nightly each named `larger` under a "Runner class" column — and a release build left on a free hosted runner was therefore reviewable as a policy violation. That inverted the epic's own direction, which is hosted first for anything that fits, the fleet for what does not, and billed minutes trending to zero.

  Two placements remain fixed, and for the same reason: the Quick tier and `advisories.yml` both run without any bound on how often they would cost money, so neither is allowed to. Every other placement is a trade of money for wall-clock, decided per repository from three facts — the lane's measured time on each class, how often it runs, and what those minutes cost in the snapshot `usage-report.yml` posts — and recorded where the lane lives. The starting points in the table are unchanged, and the shared workflows still default the lanes that compile to `larger`; what changed is that naming a hosted label instead is now a supported answer rather than a deviation, and a free lane needs no `# runner-class: larger` marker and no defence.

- **Every same-repository action reference uses GitHub's `$/` self-repository syntax, and the self-checkout it replaces is gone.** A `uses:` beginning with `$/` resolves to the running workflow's own repository at the exact commit already running. Eighteen "Checkout shared CI" steps and twenty-five hand-written relative paths are now twenty-five `$/.github/actions/…` references, and no reusable workflow checks itself out any more.

  The old approach was a workaround for a documented limitation: an action referenced as `./…` from inside a reusable workflow resolves against the *caller's* workspace, so a shared workflow could not reach its own actions without either checking itself out or naming a hardcoded commit. GitHub made the syntax generally available on 2026-07-30 and calls it the recommended way to compose actions and workflows within a repository, noting that the alternatives "quietly defeated commit SHA pinning" — which had already happened here, with one consumer pinning the workflows at one commit and a composite action at another that was never on `main`.

  Two scripts that were invoked by path rather than by reference now have composite actions of their own, `resolve-lanes` and `verify-workspace-versions`, which is what let the last two checkouts go. Neither adds logic; both keep the script's own `--self-test`.

  **This requires an Actions runner of 2.336.0 or newer.** Hosted runners update themselves. Every machine in the self-hosted fleet reported 2.337.0 when this landed, and a runner below the floor fails the step outright rather than silently. The syntax is github.com only.

  Nothing changes for a calling repository. `$/` means *this* repository, so a caller reaching into `EdgeFirstAI/.github` still writes the full `EdgeFirstAI/.github/.github/…@<sha>` form and still pins it.

- **`maturin-spec` is derived from the runner OS when it is not set**, and `release-wheels.yml`'s default is empty so that derivation is reachable. It is a property of the platform rather than of the repository: `zig` is what produces the manylinux wheels, and `patchelf` is a Linux-only PyPI package with no wheel for macOS or Windows, so a value set once for every lane is a value some lane cannot install. The per-lane override added in 1.1.0 stays for the case it is genuinely for — pinning a maturin version for reproducibility — rather than for restating a platform fact in every caller.

- **The migration order is now stated: land the workflow callers in their own pull request, before any release PR.** Section 4.5.6 requires a `publish.yml` rehearsal before a repository's first tag, and on a first migration it cannot be run at all — GitHub refuses to dispatch a workflow that is not on the default branch, and merging the release PR fires `tag-release.yml` immediately, so the file arrives and the tag is created in the same instant. ara2-rs hit this and released without the rehearsal. Splitting the migration from the release restores the window.

  The same note records what the rehearsal cannot cover in any case: a Trusted Publisher still pointing at `release.yml` is invisible to it, because a rehearsal skips the upload. ara2-rs v0.18.0 failed on exactly that, with crates.io answering `Expected workflow filenames: release.yml`. Verify the publisher configuration rather than assuming it.

- **Both fork guards fail closed on any untrusted trigger, not just fork pull requests.** Each tested `github.event_name == 'pull_request'` before deciding whether to trust a run — an allowlist of *when to check*, which silently trusted every event it did not name, so `pull_request_target` and `workflow_run` reached self-hosted capacity unguarded: the fleet, board and GPU lanes in the Rust case, and a machine shared with production Jenkins builds serving a public repository in the Yocto case. Neither workflow's checkout of the calling repository passes a `ref:`, so this was exposure of self-hosted capacity to untrusted events, not of fork-authored code — `pull_request_target` checks out the base branch and `workflow_run` the default branch, never the fork's head — but the guard step still simply skipped, which looks identical to a legitimate same-repository run.

  The default is now inverted. Only `push`, `workflow_dispatch`, `schedule` and `merge_group` are trusted outright, `pull_request` is trusted when its head repository is this one, and nothing else is. The two workflows differ in what they do about it, deliberately: the Rust lanes downgrade to hosted runners because a hosted fallback exists, while `yocto-build.yml` refuses, because there is no hosted Yocto runner to fall back to.

- **The `fleet` runner class resolves for Linux and Windows.** It never did: the class demanded a fourth capability label (`build`, `d3d11`) that no registered machine carried, so `runner-class-linux: fleet` queued until the job timed out. The machines now carry `build`, and the Windows and macOS fleet tuples ask for `build` rather than `d3d11` and `metal`. Those remain reserved for machines that genuinely have them — claiming a graphics capability a build box lacks converts a queue into a runtime failure, which is worse.

- **Lane resolution moved from inline bash into `.github/scripts/resolve_lanes.py`**, with a `--self-test` run by CI. Generalising `lanes` while guaranteeing `all`, `host` and `hardware` still behave identically is exactly the change that wants a test, and an inline `run:` block cannot have one.

- **`apply-runners.sh`'s Phase A is now authoritative, not purely additive.** It adds labels a runner's declared list is missing and now also removes custom labels the runner has that are not declared, so `runners.json` is a complete description of a runner's labels rather than a floor. Only `type: custom` labels are ever touched — GitHub's auto-assigned labels are filtered out explicitly rather than relied on to reject the removal — and a runner absent from `.labels` stays unmanaged. A runner declared with an empty list is refused with `::error::` rather than applied, since that would strip every custom label it has and is far more likely a mistake than an intention.

- **New custom labels are lowercase and hyphen-separated.** `CUDA` and `Yocto` predate the convention and keep the casing GitHub's organisation-wide label registry already has for them, unchanged everywhere they are referenced — `runners.json`, `resolve_lanes.py`, `yocto-build.yml` and the docs — since the API cannot alter a label's registered casing and declaring the lowercase form would only make the converger propose the same no-op removals and additions on every run. Actions label matching is case-insensitive, so the exception costs nothing at runtime.

- **Runners are registered with no custom labels.** Every custom label is added afterwards through the API by `apply-runners.sh`, so the converger owns all of them and restores a re-provisioned board's identity entirely from `runners.json`. `mltrain-02`, `mltrain-03` and `mltrain-04` predate the rule and were registered with `--labels`.

- **`apply-runners.sh` is ported to `.github/scripts/apply_runners.py`, and every phase is now authoritative.** The bash version could only add — POST a missing label, PUT a drifted access list, PUT a missing group member — never remove, so it converged in one direction and took four separate fix rounds to reach even that, each impossible to regression-test in bash. The port adds a `--self-test` that runs against fixtures with no credentials or network access, wired into `ci.yml` beside `resolve_lanes.py`'s.

  Four gaps close with the port. An empty declared repository list now revokes access rather than being skipped, since it is valid declared state, not "leave alone". Group `visibility` is declared in `runners.json` (`selected` for all five managed groups today) and reconciled alongside the repository list, because a group that has drifted to `visibility: all` is reachable by every repository regardless of what the access list says. Group membership is authoritative: a stale or manually-added runner sitting in a managed group is reported as a hard error naming the runner and the group rather than kept silently — the only obvious destination is `Default`, the broadly-reachable group this whole design exists to empty, so nothing moves a runner there automatically. Argument parsing is strict, so a typo like `--dryrun` can no longer fall through to a live apply; any unrecognised argument exits non-zero having touched nothing.

### Removed

- **Repository access lists on the runner groups, and the ability to declare one.** Every organisation runner group is `visibility: all` — `boards`, `build-x86`, `gpu-cuda`, `mac`, `windows`, `larger-runners` and `yocto` — with no scoped repositories on any of them. `runners.json` has no `repositories` key and no way to express one, and `apply_runners.py` drops the `SetRepositories` operation, the repository-id lookups and the `repos_ok` reporting.

  A repository access list bounds which repositories can reach a runner, never which events can: it cannot distinguish a fork's pull request from the base repository's own push, because both run under the base repository's name. Kept current against every repository in the organisation, the lists were standing maintenance against a threat they could not address.

  `runner-groups.md` now states what does bound a fork pull request, because this changelog previously implied `resolve_lanes.py` did. It hardens the shared workflows and cannot constrain a workflow that declines to use them; the governing control is the organisation's fork pull-request approval policy, which no workflow change can bypass.

  `visibility` remains declared and reconciled, so a group narrowed to `selected` through the web UI is drift the converger catches.

- **The `unmanaged` key in `runners.json`.** `mac` and `larger-runners` were exempted from the converger and documented in place; both are now declared like any other group, so every group except the built-in `Default` is reconciled. An undeclared group is where drift hides, which is the failure this file exists to prevent. Restricting billed larger runners remains the CI epic's closing ticket and now starts from an unrestricted state rather than from a stale `hal`/`packaging` list that enforced nothing.

- **The board lane's `concurrency` group.** It keyed on the label rather than the device, so it capped throughput across every machine answering that label while guaranteeing nothing the runner did not already guarantee — a runner executes one job at a time per installed instance. With family labels, `boards: imx8mp` will match every i.MX 8M Plus carrier, and the group would have serialised all of them. Per-device grouping is inexpressible, since concurrency is evaluated before a runner is selected. One runner instance per device is now stated policy and is the guarantee that matters.

- **`.github/runners/provision-*.sh`.** They described an ephemeral, container-based, group-assigned fleet that no machine was ever built from — the real machines are stock installs registered as services with `svc.sh`. Scripts that document a fleet that does not exist are worse than no scripts; the install procedure lives in Confluence.

- **`apply-runners.sh`**, replaced by `.github/scripts/apply_runners.py`.

### Fixed

- **`resolve-lanes` declared no outputs, so `rust-full.yml` resolved every lane to the empty string.** The lane setup job publishes fourteen outputs — the four runner labels, the CUDA labels, seven `do_*` gates, `same_repo` and `board_matrix` — all read from the step that calls this action. Moving the script out of an inline `run:` step and into a composite action changed where those reads resolve, and the action declared none of them, so each evaluated to `''`: every `if: ... == 'true'` was false and the whole Full tier skipped while reporting success. The action now declares all fourteen, and the check above keeps it that way.

- **The mirror never asserted that the digest survived the copy.** The source promotion fails if `imagetools create` changes a digest; the mirror performed the same operation against a different registry and checked nothing. A destination that rewrites a manifest therefore left the mirror serving an image the published digest does not identify, with the run green. The mirror now makes the same assertion as the source.

- **A container release built an invalid image name in `templates/release-container.yml`.** `github.repository` preserves the owner's casing, and this organisation's name is not lowercase; an OCI repository name must be. A copied skeleton pushed `ghcr.io/EdgeFirstAI/...` and failed in the registry rather than in buildx. The name is normalised once, before login, build and recording, and `record-image-digests` normalises what it records so the manifest matches what was pushed.

- **An `images` input of only comments recorded an empty digest manifest.** The non-whitespace guard passed, every line was skipped, and the "a release that pushed nothing is not a release" failure was deferred to promotion — after the tag exists. The recorder now rejects an empty entry set on the release branch.

- **Three JSON inputs were consumed by `jq` inside a process substitution, where `set -e` cannot see it fail.** `aliases`, `mirror-images` and `payloads` each fed a `while read` loop from `< <(jq ...)`. A malformed value made the loop body never run and the step succeed: no alias moved, no payload downloaded. `mirror-images` failed worse — the `length` test yielded an empty string, `[[ "" -eq 0 ]]` is arithmetically true, and a malformed selection mirrored every image instead of the named ones. An element of `aliases` missing `alias` or `from` rendered as the string `null` and pushed a tag called `null`. All three are now validated for type and shape before the loop, by a `jq -e` whose exit status is actually tested.

- `release-wheels.yml` attested before the caller's `post-command` ran, so a wheel that the assertion was about to reject already carried provenance. This is correct when `maturin-build` is called directly—it attests what it built—but wrong through this workflow, which has a rejection step after it. The workflow now passes `attest: false` and attests itself, after `post-command` and before the upload, so provenance covers exactly the set that reaches the artifact store. hal worked around this by hand; a caller should not have to know to.

- **`tag-release.yml` verified the build against one commit and tagged another.** The build runs on the release-branch head; the tag goes on the merge commit. Those carry the same tree only while `main` has not moved, and when it has, the tag names a tree no build ever produced — which `publish-rust.yml` rejects by design, but only once the tag exists and the release ruleset has made it immutable. The design answered this with "require branches to be up to date before merging", a repository setting nothing verifies. The enforcement is in two places, because the two have different powers.

  `rust-full.yml` refuses a release pull request whose branch is behind its base. That is the same condition while it is still cheap — the branch gets updated, the push rebuilds it, and the merge then carries the tree that was built. It is the check that can actually be acted on.

  `tag-release.yml` compares the head and merge trees and refuses to tag a mismatch. It runs on `pull_request: closed`, so by then the merge has happened and there is no "merge again"; it is a backstop against a release PR that skipped Full, and its message now spells out the real recovery — point the release branch at the merge commit so `release.yml` builds that exact tree, then create the tag through the organisation tag-ruleset bypass, the route a maintenance tag already uses. Runs wherever `require-build` is set, which is the signal that a repository is on the release chain.

## [1.1.0] - 2026-09-18

Everything here is exercised by a real release: `EdgeFirstAI/ara2-rs` v0.18.0 was built on a release branch, tagged on merge and published from those artifacts, using these workflows at 68dd89a — which is this tag. That migration is also what found most of what follows.

### Added

- **`release-wheels.yml`, the maturin wheel build every binding repository was writing for itself.** Six repositories carry their own copy of the same matrix — `hal`, `client`, `profiler`, `schemas`, `tflite-rs` and `ara2-rs` — and the wheel build is also where the tag-path failures were: a runner image without `git-lfs`, the same image without a C compiler, a toolchain component conflict. Those are properties of the build environment rather than of any one repository, so they are now fixed in one place. It takes a `runners` matrix (defaulting to manylinux2014 on x86_64 and aarch64 Linux with the sdist on x86_64, on the `larger` class the runner policy specifies for a release build), a `features` list for `pyo3/abi3-*`, and the `env` and `pre-command` hooks. Every step declares bash, since an overridden matrix may name a Windows image where the default shell is PowerShell. The C compiler it needs is guaranteed by `setup-rust`; it checks `git` itself, because maturin shells out to it for a vendored source. It checks each built wheel's version against the release branch: a wheel's version comes from the manifest, but a binding deriving it some other way can still produce a wheel naming a version the release is not, and a PyPI version is immutable once uploaded.

- **A `runners` entry may override `maturin-spec`**, which is what a repository shipping both Linux and non-Linux wheels needs. `zig` is what produces the manylinux wheels, and `patchelf` is a Linux-only PyPI package with no wheel for macOS or Windows, so a single workflow-level specification cannot serve both: hal installs `maturin[patchelf,zig]` on its two Linux lanes and plain `maturin` on macOS and Windows. `pre-command` is not a workaround, because it runs before `setup-python` — an install there lands in the system interpreter and the workflow's own install step overwrites it afterwards. This was the last input keeping `hal`, the repository with the largest wheel matrix in the fleet, on its own copy of the build.

- **`builds` and `post-command` on `release-wheels.yml`**, both from reviewing it against `hal`.

  `builds` is a JSON array of `{manifest, features, args}` looped inside one job. The reusable-workflow boundary is per job, so one call per binding means one job per binding: hal ships five distributions and builds each for `abi3-py311` and `abi3-py38`, which is forty jobs across four platforms against the four it runs today — each paying its own checkout, toolchain, cache restore and link, and none of them sharing a `target/` or a warm cache. Looping inside the job keeps both. A `runners` entry may carry its own `builds`, which is how a caller produces the sdist on one platform only. `manifest` remains the simple form for a repository shipping one binding.
- **`package-env` and `package-pre-command` on `release-rust.yml`.** The packaging job runs `cargo package --locked` without `--no-verify`, so it performs Cargo's verification compile — which means a crate whose build scripts need an OpenCV root, a sysroot or an ANGLE path cannot use the required packaging path at all, since a reusable workflow inherits nothing from the caller's job. Every other compiling lane already had `env` and `pre-command`; this one did not. The packaging job also declares `bash`, because `package-runner` is caller-overridable and may name a Windows image.

  `post-command` runs the caller's own assertions over the built wheels, after the build and **before** the upload. There was no counterpart to `pre-command`, and the ordering is the point: `publish.yml` ships what the build produced without re-examining it, and a PyPI version is immutable, so a wheel that fails an assertion must never reach the artifact store. hal is the motivating case — rustc strips Apple binaries with its own in-process Mach-O writer, which leaves the LINKEDIT string pool 4-byte aligned whenever a binary's `nindirectsyms` is odd, and dyld on macOS 26+ then refuses to load the wheel. The parity is a coin flip per binary, so an import smoke test on one build proves nothing about the next; the check parses every wheel instead.

- **`crate-packages` on `release-rust.yml`, which runs `cargo package --locked` and uploads the `.crate` files.** `publish-rust.yml` runs `cargo publish --no-verify`, and `--no-verify` is only defensible because packaging was already exercised on a reviewable branch — but nothing did it, so an excluded file, a path dependency without a version or a dirty tree still surfaced inside `cargo publish` on the tag. `release-rust.yml` records the resolved list beside the `.crate` files, and `publish-rust.yml` reads that recorded list rather than trusting its own input: a caller value that differs fails the publish, so packaging `foo` and publishing `bar` is not expressible rather than merely discouraged. `package-crates` mirrors `publish-crates` for a repository that publishes no crate. The packaging job runs on the `larger` class, because `cargo package` compiles.

- **`cross-clippy-args` on `rust-quick.yml`.** The per-target pass was a fixed argument list, so a workspace containing one crate that cannot cross-compile — a PyO3 extension with no interpreter for the target, anything needing a sysroot — had `skip-cross-clippy` as its only escape, and paid for it by losing aarch64 lint coverage entirely. That is the wrong trade for a fleet whose products are aarch64. The pass is now `cargo clippy --target <triple> <cross-clippy-args>`, so a caller narrows it with `--exclude` instead of switching it off.

- **`clippy-extra-args` on `rust-quick.yml`**, a second host pass that runs only when set. A crate whose off-by-default features gate real code gets no pull-request signal from the default pass, and the nightly feature-combination lane is up to a day away.

- **`env` on `rust-quick.yml`, `rust-full.yml` and `release-wheels.yml`.** Build configuration a lane cannot infer — `PYO3_CROSS_*`, OpenCV and CUDA roots, sysroot paths — was reaching the lanes as `pre-command: echo FOO=bar >> "$GITHUB_ENV"`, a shell hack standing in for a missing input. Values are appended verbatim, never interpolated into a script, and a line that is not `KEY=VALUE` is rejected rather than silently dropped. `pre-command` is for work; `env` is for configuration. On `rust-full.yml` it applies to every lane including the board.

- **`workflow-lint`, a composite action running actionlint and the SHA-pin policy, wired into `rust-quick.yml`.** Hash-pinning every action is a standing requirement that nothing enforced outside this repository, so a floating reference survived in a product repository until somebody happened to read the file — `lidarpub` and `radarpub` between them carry dozens, including a `@master` Sonar action. This repository's own pin check moved out of an inline block in `ci.yml` and into `.github/scripts/check_action_pins.py`, so the policy has one implementation rather than a copy here and a copy per caller. actionlint itself is pinned by version and by SHA256 per platform — Quick runs on `ubuntu-24.04-arm` in some callers — and the verified archive is always downloaded rather than deferring to a copy already on `PATH`, whose provenance is unknown. A `docker://` reference is not exempt from the policy either: it must carry an immutable `@sha256:` digest.

- **`require-lockfile` on the `setup-rust` action, on by default.** Every shared lane passes `--locked`, so a repository that gitignores `Cargo.lock` fails with cargo's own "cannot create the lock file" — accurate, but it reads as a cargo problem rather than the CI contract it is, and it lands after the toolchain and cache steps have already run. The check names the cause and says what to do.

- `publish-rust.yml`, the tag side of the release chain, and the rule it exists to enforce: **a tag deploys and never builds.** It resolves the `release.yml` run that built the tag's artifacts, binds that run to the tag, downloads the artifacts, publishes crates via OIDC and creates the GitHub Release. It compiles nothing except `cargo publish --no-verify`, which has no pre-built input and is bounded by the release branch having already packaged and tested the same tree. A missing artifact, an expired artifact or a binding mismatch fails the publish; there is deliberately no fallback to a build, because a deploy-only pipeline that cannot prove which build it is shipping is worse than one that rebuilds.

  The binding is by **tree SHA, not commit SHA**. A squash merge gives the merge commit a different SHA from the release branch head while the tree is identical, so commit equality would reject every squash-merged release. Checking the tree also passes only when the release branch was up to date with `main` at merge, which is what a release wants anyway, so the check doubles as enforcement rather than merely as a guard.

  Publishing is gated inside the shared workflow on `github.event_name == 'push'` and a `refs/tags/` ref, not in the caller. A `workflow_dispatch` therefore resolves, verifies, downloads, renders the release notes and publishes nothing — a complete rehearsal of the publish path at no cost and with no tag — and a caller cannot remove that gate by editing its own file.

- `templates/publish.yml`, and `templates/release.yml` rewritten as the release-branch build. The two carry the migration hazard that neither a rehearsal nor CI can catch: PyPI and crates.io Trusted Publishers match on workflow **filename**, so splitting the chain breaks every publisher configuration until it is re-pointed from `release.yml` to `publish.yml`, and a rehearsal skips the upload. Re-point first, dispatch second, tag third.

- `resolve-release-build`, a composite action holding the part of the publish side that is identical everywhere: find the release-branch build run for a tag, bind it by tree SHA, and refuse an expired one. It needs no checkout, which is what lets a rehearsal run before the tag exists, and `publish-rust.yml` is now a consumer of it rather than the only home for it.

  Extracted because the first real migration does not fit the reusable workflow. hal publishes five PyPI distributions through separate environments in dependency order, ten crates in an order that encodes which optional dependency broke v0.29.3, and a GitHub Release carrying build provenance, checksums and NOTICE. That is repository-specific mechanics and belongs in hal. The resolve is not, and duplicating it there would mean fixing the next binding bug twice — five of the ten review findings on the split were in that logic, which is the argument for having exactly one copy of it.

- `require-build` on `tag-release.yml`: no tag is created unless the named workflow is green for the exact commit being merged. Branch protection requires `ci-gate` and nothing else, and the release build runs on a branch push rather than on the pull request, so a release PR can merge while its build is pending or red — "the artifacts exist before the tag does" was a claim with nothing behind it. Refusing the tag is where it is enforceable: a merged PR with a broken build now leaves no tag rather than a tag whose artifacts do not exist. Defaults to empty so a repository whose release still builds on the tag is not blocked mid-migration; `templates/tag-release.yml` sets it.

- `retention-days` on `sbom.yml` and the `sbom-tools` action, and the release SBOM set to 30. Full-mode SBOMs uploaded at the CI default of 7 days, but `publish-rust.yml` requires the SBOM and runs after the release PR merges, which is human-paced: a release held for more than a week would have failed at publish with its product artifacts still present.

- `release/X.Y.Z-rcN` branches in `tag-release.yml`, producing `vX.Y.Z-rcN`. The suffix is restricted to `-rc<digits>` rather than the full SemVer pre-release grammar because the derived version is written unquoted to `GITHUB_OUTPUT`, and the anchored pattern is what stops a branch name forging a second output. `publish-rust.yml` marks such a tag as a GitHub pre-release and never moves `latest` onto it; the previous "latest" computation compared with `sort -V`, which ranks `0.33.0-rc1` above `0.32.0` and would have made a release candidate the latest release.

  A candidate reaches crates.io and PyPI **only when the manifest version is exactly the tag version**. Registry versions are immutable, so tagging `v1.2.0-rc1` while the manifests still say `1.2.0` would publish `1.2.0` and leave the final release with no version to claim — an unrecoverable outcome reached by following the documented flow. The check is mechanical rather than an input: exact match uploads, base version gets a GitHub pre-release with every artifact and a skipped registry step, and the release branch says so up front rather than the tag discovering it.

- A changelog-section check on the release branch. `publish.yml` builds the GitHub Release body from the `## [X.Y.Z]` section, and an absent section previously produced a release with empty notes, discovered after the tag existed. It is now a red release PR. A `-rcN` branch is checked against its base version, since a candidate does not get its own section.

- `NCSA` to the license policy's allowed list. The University of Illinois/NCSA Open Source License is OSI-approved and permissive, combining the MIT and BSD-3-Clause terms, and is satisfied by attribution alone. It is the licence LLVM used before moving to Apache-2.0 with the LLVM exception, both forms of which the list already allows. Reached today through `libfuzzer-sys`, a `cfg(fuzzing)` dependency of `rav1e`; a permissive licence blocking a build is a gap in the list rather than a finding about the dependency.

- `targets` and `extra-manifests` on `sbom.yml` and the `sbom-tools` action, for the dependency-graph scan. Both default to empty, so no existing caller changes. A dependency graph is resolved per target, and `cargo cyclonedx --all` sees only the workspace, which leaves two holes in what an SBOM is supposed to describe. A host-only scan on a Linux runner cannot reach a target-conditional dependency -- in hal that is the fourteen `windows-*` crates, every one of them shipped in the Windows C archive and the Windows wheels, none of them in the SBOM. And a package excluded from the workspace is invisible to `--all` even when it is the *shipped* artifact: hal's five `-capi` cdylibs are each a standalone package with its own lockfile, and they are what the C archive contains. `targets` accepts triples or cargo-cyclonedx's own literal `all`, which is usually what you want -- naming a dependency that never ships costs nothing, omitting one that does is the defect. A target needs no toolchain installed, since `cargo metadata`'s platform filtering resolves it from the registry, so one Linux runner can produce the Windows, macOS, iOS and Android graphs.

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

- `templates/release.yml` calls `release-rust.yml` with `crate-packages` and adds a `release-wheels.yml` job, so a repository adopting the template gets crates and wheels from the shared implementation and writes only what is genuinely its own — C API archives, container images, binaries.

- `release-rust.yml` is now the **release-branch** side of the chain and no longer runs on a tag. It verifies version consistency across `Cargo.toml`, `pyproject.toml` and `VERSION` against the branch name, checks the changelog section, and produces the full SBOM. Callers trigger it from `on: push: branches: ['release/*.*.*']`.

  It runs on `push` rather than `pull_request` deliberately. A `pull_request` run builds a merge-preview commit that exists nowhere in history, so its artifacts could never be bound to the tag; a `push` run builds the branch head, which is the commit the release PR merges.

- `templates/` now pins every `EdgeFirstAI/.github` `uses:` to an all-zero placeholder instead of a real commit, and a new lint step enforces it. The pins had drifted to a commit from nine months ago, which is worse than it sounds: a stale SHA still *resolves*, so a copied skeleton silently ran old CI. This change made the failure mode concrete -- the skeleton referenced `advisories.yml`, which does not exist at the old pin, and forwarded a `force` input the old `nightly-gate` does not declare. An unresolvable ref fails immediately and says what to fix. Third-party actions in `templates/` keep real pins and can still be copied as-is.

- `rust-full`'s `nightly-extra` job no longer runs `cargo audit`; that moved to `advisories.yml` so it is not gated. The job is now named **Feature combinations**, which is all it still does, and it skips entirely when `hack-args` is empty rather than booting a runner to install tools and run nothing. Callers wanting advisory scanning must add the `advisories.yml` job, as `templates/nightly.yml` now does.

- `nightly-gate` now actually skips. Two things stopped it. It only applied its "has main moved" check on `schedule`, so a `workflow_dispatch` bypassed it silently and re-dispatching a nightly rebuilt the same commit, re-running the board -- the slowest and only hardware-bound lane -- for no new information. And it compared against the last **successful** run, which in a repository whose nightly is not consistently green means comparing against an arbitrarily old commit: hal's last green nightly on main was 2025-12-08, so the gate had not skipped once in nine months. The check now applies to every trigger and compares against the last run that reached a **verdict** -- `success` or `failure`, since both mean the lanes ran and reported. Other conclusions are discarded, `cancelled` above all: a run can be cancelled before a single lane starts, so it proves nothing about its commit, yet it is still "completed" at that sha and would otherwise suppress the next night.

  A new `force` input runs anyway. It is the only way to re-run an unchanged commit, which makes it the way to re-try after fixing a lane rather than the code. Callers that do not pass it get `false`. `templates/nightly.yml` forwards it as `${{ inputs.force || false }}` -- the fallback is required, because `inputs` is null on a schedule trigger.

- Runner policy is now per tier rather than a single cost-first ordering.
  Quick stays on free standard runners and never bills; Full and Release
  default to `larger`, which is what they were before this migration. Moving
  those lanes to standard runners to save money made hal's Full tier slower
  than the 15-to-20-job workflow it replaced, which is a failed migration, not
  a saving. The `larger` class maps to `ubuntu-24.04-xlarge` /
  `ubuntu-24.04-arm-xlarge` to match the hosted class.

### Removed

- The `wheels`, `c-archive`, `crates` and `github-release` jobs from `release-rust.yml`. The two publish jobs moved to `publish-rust.yml` unchanged in substance. The two build jobs were deleted rather than moved, and the build now stays in the product repository.

  They had never run. `release-rust.yml`'s only caller was `ci-foundation-scratch`, which has no tags, so the workflow was never executed in any repository, and that caller still passed a `shared-sha` input removed in #22 — it would have failed on first use. EDGEAI-1553's acceptance criterion that a scratch repo complete `release/X.Y.Z` PR → merge → auto-tag → release dry run was therefore never met, which is how a release path shipped in 1.0.0 with no evidence behind it.

  Nor could they have worked. `wheels` was a four-way `uvx maturin build` matrix and `c-archive` fell back to tarring the whole of `target/release`, intermediates included. The build is the one genuinely repository-specific part of a release: hal ships five wheels across eight targets plus ten C-API archives with codesigning, schemas ships ten wheels, videostream ships C. A shared matrix guessing at that is wrong for every caller, and a wrong shared job is worse than no job because the next migrator assumes it works. What is shared is everything around the build — version consistency, the changelog contract, the SBOM, and the whole publish side.

  Two rules make a repository's own build work with `publish-rust.yml`: `retention-days: 30` or more, because the release-PR-to-tag gap is human-paced and publish fails on an expired artifact rather than rebuilding; and `if-no-files-found: error`, because a silently empty artifact is a silently incomplete release.

### Fixed

- **A lane on an organisation larger runner could fail before it ran anything, with `linker "cc" not found`.** The GitHub-hosted images provide a C compiler; `ubuntu-24.04-arm-xlarge` is a different build and does not. Rust links through `cc` and any dependency with a build script needs one, so every build script in the workspace failed to compile — measured on EdgeFirstAI/ara2-rs run 35382211407, the first repository to put Full on the larger class. `release-wheels.yml` already installed it, which is why the wheel lanes passed on the same image while the test lane died; the guarantee now lives in the `setup-rust` action instead, so all eleven call sites across six workflows get it from one implementation rather than each lane growing its own copy. `require-cc` turns it off. The probe is per platform: Linux installs, macOS reports and stops because the Xcode command line tools are part of the image, and Windows is not probed at all — its toolchain is MSVC, which presents as `cl.exe` and is normally not on `PATH`, because the `cc` crate locates it through vswhere and the registry.

- **The cross-clippy pass failed on any workspace with a dependency that has a build script.** A check-only pass still compiles build-script C *for the target*, and rustup's std for a triple is not a C toolchain for it: cc-rs looks for `<triple>-gcc` and fails the lane when it is absent. `setup-rust` takes `cross-cc-targets`, installs the matching cross package for the triples it knows — aarch64, armv7/arm, riscv64 — and sets `CARGO_TARGET_<TRIPLE>_LINKER`. An unrecognised triple is a notice rather than a failure, since the image may already carry it. `rust-quick.yml` passes its `cross-targets` through, so the lane a caller could previously only disable with `skip-cross-clippy` now works.

- **`templates/ci.yml` declared `permissions` at workflow level**, which every job inherited whether it used them or not. SonarCloud reports it as `githubactions:S8264` and it fails a quality gate on the repositories that have one. Each job now declares what it uses, and `ci-gate` — which reads its own `needs` context and nothing else — declares none.

- The wheel build no longer demands `cc` on Windows, where the toolchain is MSVC and the check rejected an image that builds perfectly well — the one platform the `runners` matrix had just been made safe for. That rule now lives in `setup-rust` with the rest of the compiler probe, and the wheel lane checks only `git`, which is its own concern: maturin shells out to it for a vendored source.

- **`setup-rust` now installs the toolchain the repository pins, instead of `stable` plus whatever `rust-toolchain.toml` makes cargo switch to.** It passed no `toolchain:` to `dtolnay/rust-toolchain`, whose default is the literal `stable`, so a pinning repository fetched two toolchains and — the part that matters — `components` and `targets` landed on the one cargo would not use. It worked only because `hal` and `ara2-rs` both list `rustfmt` and `clippy` in their toml; a repository pinning a channel without that list reaches `cargo clippy` with no clippy installed. The channel is now read from `rust-toolchain.toml` (or the legacy plain-text `rust-toolchain`), in either TOML string form, falling back to `stable`.

- **`verify-version` checks a workspace's internal crate versions.** It read the first `^version =` in the root `Cargo.toml` and nothing else, so a workspace versioning its members through `[workspace.dependencies]` could bump `[workspace.package]` alone and pass. The result is not a failed release: each member then depends on the *previous* release of its sibling, a version that exists on crates.io, so `cargo publish` accepts it and ships a wrong dependency graph. Nothing downstream catches it either, because `cargo package` resolves the path dependency locally. Every `[workspace.dependencies]` entry carrying both `path` and `version` is now checked against the branch version; third-party entries are left alone. The manifest is parsed rather than scanned, because Cargo accepts `[workspace.dependencies.foo]` as a table with separate keys and a line-oriented check sees only the inline form.

- **The SonarCloud job no longer boots a runner for a repository with no SonarCloud project.** Only the scan step was gated on `sonar-project.properties`, so the job still started, checked out, downloaded every coverage artifact and merged lcov before skipping the one step that mattered. `hashFiles` is not available in a job-level `if`, so the `setup` job answers the question as an output. Callers no longer need to know to pass `sonar: false`.

- The GitHub Release notes parser matched a version **prefix**, so release `1.2.3` extracted the `## [1.2.30]` section and shipped another release's notes. Carried in from the 1.0.0 release workflow and now fixed in both places that read a changelog section, which require a complete bracketed or unbracketed version token.

- The pre-tag rehearsal could not run before the tag existed. `publish-rust.yml` checked out the tag as its first act, so a dispatch for `vX.Y.Z` failed on an unresolvable ref — the rehearsal was only usable *after* the thing it exists to de-risk. It now resolves the build first and binds against the release branch head when the tag is absent, which catches the same "something was not built" failure, and against the tag once one exists.

- `publish-rust.yml` only considered `push` runs of the build workflow, so a `workflow_dispatch` rebuild of a release branch — which `templates/release.yml` advertises — could never replace a failed or expired one. The event filter is gone; the branch and tree checks are what bind a run to the release.

- The caller's `publish-pypi` job was skipped entirely during a rehearsal, so a rehearsal could pass with no wheels at all and leave that discovery to the real tag, after the crates had published. It now downloads and collects in rehearsal mode and gates only the upload step.

- `templates/release.yml` introduced a second `EdgeFirstAI/.github` pin as a `ref:` on a composite-action checkout. The `uses:` pin is meant to be the only place the shared commit appears precisely so Dependabot's bump is complete; a second one drifts silently and mixes versions, and following the template's own header instruction left it at the all-zero placeholder. Removed.

- The dependency SBOM merged every `*.cdx.json` in the tree rather than the scans it had just produced. cargo-cyclonedx writes one file per package beside its manifest, and a `--target` run writes another per package per target; they are build residue and usually gitignored, so a working tree accumulates scans from older dependency graphs while `git status` stays clean, and the SBOM became the union of every graph ever scanned there. Measured in hal: 360 components on a working tree against 237 on a fresh checkout, the surplus including `crossbeam-epoch` 0.9.18 and `pyo3` 0.29.0, versions no current lockfile pins. CI never saw it, because its checkout is clean -- so the policy gave a different answer locally than it did in CI on the same commit, which is the worst way for a compliance artifact to be wrong. Each run now writes its scans under a run-unique `--override-filename` and merges exactly those, making provenance structural rather than inferred from timestamps, and removes only the files it created: a caller's own residue is left exactly as it was found.

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

[2.0.0]: https://github.com/EdgeFirstAI/.github/compare/v1.2.2...v2.0.0
[1.2.2]: https://github.com/EdgeFirstAI/.github/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/EdgeFirstAI/.github/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/EdgeFirstAI/.github/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/EdgeFirstAI/.github/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/EdgeFirstAI/.github/releases/tag/v1.0.0
