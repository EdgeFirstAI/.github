# EdgeFirstAI shared CI

Reusable GitHub Actions for EdgeFirst and Maivin repositories. Product repos call these workflows by **commit SHA** (tag recorded in a comment). This repository is public so other public repos can `uses:` it.

Design: [CICD Pipelines](https://au-zone.atlassian.net/wiki/spaces/EAM/pages/2750906369/CICD+Pipelines) Ticket: [EDGEAI-1553](https://au-zone.atlassian.net/browse/EDGEAI-1553)

The organisation profile README lives in [`profile/`](profile/README.md).

## Layout

| Path | Purpose |
| --- | --- |
| `.github/workflows/rust-quick.yml` | fmt, clippy, nextest, dependency license |
| `.github/workflows/rust-full.yml` | host matrix, boards, coverage, scancode |
| `.github/workflows/python-quick.yml` | ruff + pytest |
| `.github/workflows/python-full.yml` | pytest with coverage across a Python matrix, SonarCloud |
| `.github/workflows/cmake-quick.yml` | ccache + ctest |
| `.github/workflows/nightly-gate.yml` | skip nightly when `main` is unchanged |
| `.github/workflows/advisories.yml` | `cargo audit`, run ungated so a new advisory is still reported |
| `.github/workflows/yocto-build.yml` | Yocto bitbake on the dedicated builder; fork-refusing and serialised |
| `.github/workflows/sbom.yml` | `dependency` or `full` scancode |
| `.github/workflows/tag-release.yml` | `release/X.Y.Z[-rcN]` merge → annotated `vX.Y.Z[-rcN]` |
| `.github/workflows/release-rust.yml` | release-branch side: version consistency, changelog section, `cargo package`, SBOM |
| `.github/workflows/release-wheels.yml` | release-branch side: maturin wheels for a PyO3 binding, built on the `maturin-build` action |
| `.github/workflows/publish-rust.yml` | tag side: resolve the build, verify the tree, crates OIDC, GitHub Release |
| `.github/workflows/publish-container.yml` | tag side: promote the release build's recorded image digests, unchanged |
| `.github/workflows/release-image.yml` | release-branch side for a single-Dockerfile image: build, push the candidate to the app's ECR repository, record its digest |
| `.github/workflows/studio-app.yml` | on demand: register a published version on one Studio server, by digest, from its `studio-<server>` environment |
| `.github/actions/` | `setup-rust`, `setup-python-uv`, `codeartifact-login`, `sbom-tools`, `board-run`, `resolve-release-build`, `resolve-lanes`, `verify-workspace-versions`, `maturin-build`, `wheel-data`, `stage-pypi`, `record-image-digests`, `registry-login`, `workflow-lint` |
| `.github/scripts/` | license policy, the SHA-pin check, the workspace version check, lane resolution, wheel data staging, the runner-fleet converger (single copy each) |
| `.github/rulesets/` | `protect-main` (reviews; org-admin PR bypass), `protect-main-ci` (ci-gate, no bypass), `protect-release-tags` |
| `.github/rulesets/runners.json` | declarative runner *group settings* only (visibility, public-repository access) — no runner names; see `runner-groups.md` |
| `templates/` | per-repo `ci.yml` (`ci-python.yml` for a pure-Python repository), `nightly.yml`, `release.yml`, `tag-release.yml`, `publish.yml`, the container set `release-image.yml` (one Dockerfile) or `release-container.yml` (several images) / `publish-container.yml` / `studio.yml`, plus `CODEOWNERS` and `dependabot.yml` |

## Pinning

```yaml
uses: EdgeFirstAI/.github/.github/workflows/rust-quick.yml@eec0cb31b6576a47735099b91e39a9bdb5fbde3a
```

The `uses:` pin is the only place the shared commit appears, and Dependabot bumps it. CI rejects tag refs such as `@v1.0.0`.

Internally each shared workflow reaches its composite actions with GitHub's self-repository syntax, `uses: $/.github/actions/…`, which resolves to the running workflow's own repository at the exact commit already running. There is no second reference to keep in sync with the `uses:` pin above, and no self-checkout. It needs an Actions runner of 2.336.0 or newer and is github.com only.

`$/` means *this* repository, so it is for the shared workflows' own use. A product repository still writes the full `EdgeFirstAI/.github/.github/…@<sha>` form.

## Tiers and labels

- **Quick** — every non-draft PR push.
- **Full** — label `ci:full` (or `ci:hardware` for boards only).
- **Nightly** — schedule, only if `main` moved.

`ci-gate` is the only required check. See [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## Runner classes and capability lanes

`runner-class-linux` (and `-linux-arm`, `-macos`, `-windows`) selects a **cost** tier: `hosted` (default, free), `fleet` (our metal), or `larger` (billed). Capability is a separate axis: `lanes` is a comma-separated set of `host`, `hardware` and `gpu`, where `all` means `host,hardware` and never implies `gpu`. Board hardware is named through `boards:`: comma-separated entries, each one or more labels joined by `+` that one runner must all carry (`imx8mp-evk, imx95-frdm+ara240`). An on-demand workflow that selects boards itself uses the `resolve-boards` action, which takes the same syntax and, given a token that can read the organisation's runners, reports entries no online runner can serve instead of letting them queue.

The billed `larger` class is **available** to the Full, Release and Nightly tiers, not mandated by them. Quick never bills; everything else is a trade of money for wall-clock that a repository makes from its own measured build times, and a release build left on a free runner is a valid outcome of that trade rather than a policy violation.

The billed larger runners currently sit in the `Default` group, so they are **not** restricted to particular repositories. Restricting them is the closing ticket of the CI epic. See [`.github/rulesets/runner-groups.md`](.github/rulesets/runner-groups.md).

## Private Python packages (CodeArtifact)

`python-quick.yml`, `python-full.yml` and `release-image.yml` can read private Python packages, such as `edgefirst-model-sdk`, from AWS CodeArtifact. Four optional inputs turn it on; with `codeartifact-role` empty nothing changes.

| Input | Meaning |
| --- | --- |
| `codeartifact-role` | IAM role ARN that can read the repository, assumed through GitHub OIDC. Pass a repository variable, e.g. `${{ vars.CODEARTIFACT_READ_ROLE_ARN }}` |
| `codeartifact-domain` | CodeArtifact domain, e.g. `edgefirst` |
| `codeartifact-repository` | CodeArtifact repository, e.g. `dve` |
| `aws-region` | Region of the domain, e.g. `us-west-2`; empty uses the organisation variable `AWS_REGION` |

The call site grants `contents: read` and `id-token: write` (plus `pull-requests: read` for `python-full`'s SonarCloud job). The Python test jobs declare no permissions of their own, because a nested job may not ask for more than its caller holds: declaring `id-token: write` there would fail every caller that does not use CodeArtifact. They take exactly what the call site grants, so grant no more than that.

The role lives in terraform (DE-3119). Its trust policy names each repository that may assume it, explicitly and never by wildcard: most EdgeFirstAI repositories are public, and a wildcard would let any of them read the private packages. It needs `codeartifact:GetAuthorizationToken`, `sts:GetServiceBearerToken`, `codeartifact:GetRepositoryEndpoint` and `codeartifact:ReadFromRepository`. A pull request from a fork gets no OIDC token, so it cannot read CodeArtifact and fails at the login step with that reason.

The `codeartifact-login` action assumes the role, requests a token, masks it and clears the role's AWS credentials from the environment. Later steps hold only the token.

**Tests (`python-quick`, `python-full`).** A 15-minute token is exported as `UV_INDEX_CODEARTIFACT_USERNAME` and `UV_INDEX_CODEARTIFACT_PASSWORD` before `uv sync`. uv applies them to the index named `codeartifact`, so `pyproject.toml` declares that index and routes only the private packages to it; everything else still comes from PyPI:

```toml
[[tool.uv.index]]
name = "codeartifact"
url = "https://edgefirst-<account>.d.codeartifact.us-west-2.amazonaws.com/pypi/dve/simple/"
explicit = true

[tool.uv.sources]
edgefirst-model-sdk = { index = "codeartifact" }
```

`explicit = true` keeps uv from looking for any other package there, and the source pins the private package to it, so a same-named package on PyPI is never used. The dependency licence check builds its environment from `uv.lock` the same way.

**Images (`release-image`).** A one-hour token goes into a `pip.conf` (mode 0600, under `RUNNER_TEMP`, outside the build context) whose `index-url` points at the repository. The repository upstreams PyPI, so that one index serves every package. The build receives the file as the BuildKit secret `codeartifact`, and the file is deleted afterwards:

```dockerfile
RUN --mount=type=secret,id=codeartifact,target=/etc/pip.conf \
    pip install --no-cache-dir .
```

A secret mount is never written to a layer. Never pass the token as a build argument or set it with `ENV`.

## Release chain

Three workflows, one action each. **A tag publishes; it never builds, and it never deploys to Studio.** A Studio app adds a fourth, `studio.yml` (`studio-app.yml`), dispatched to deploy an already published version to one Studio server.

| Caller | Trigger | Action | Shared workflow |
| --- | --- | --- | --- |
| `release.yml` | push to `release/*.*.*` | **build** every artifact | `release-rust.yml` (verify + `cargo package` + SBOM) and `release-wheels.yml` (wheels); anything else stays in the product repo |
| `tag-release.yml` | `release/*.*.*` PR merged to `main` | **tag** | `tag-release.yml` |
| `publish.yml` | push of a `v*.*.*` tag | **publish** what was built | `publish-rust.yml` |

1. PR `release/X.Y.Z` (or `release/X.Y.Z-rcN`) → `main` with `ci:full`. Every push to that branch builds the artifacts and uploads them with `retention-days: 30`.
2. Merge. The shared tag workflow creates an annotated `vX.Y.Z` using `RELEASE_TAG_TOKEN` — but only if `release.yml` is green for the release-branch head being merged, when the caller sets `require-build: release.yml`. Branch protection requires `ci-gate` and nothing else, and the release build runs on a branch push rather than on the PR, so merging is not itself blocked; refusing the tag is where "the artifacts exist before the tag does" is enforced. A merged PR with a red build leaves no tag rather than a tag nothing can honour.
3. The tag runs `publish.yml`. It finds the `release.yml` run for the matching branch, checks that run's **tree SHA** equals the tag's — a squash merge changes the commit but not the tree — downloads the artifacts and publishes. A missing artifact, an expired artifact or a tree mismatch fails the publish; there is no fallback to a build.
4. `cargo publish --no-verify` is the one exception, because `cargo publish` has no pre-built input. crates.io trusted publishing uses the **caller** `workflow_ref` and environment `crates-io`.
5. PyPI trusted publishing **cannot** use a reusable workflow. The caller keeps a `publish-pypi` job: `stage-pypi` selects and verifies, then `pypa/gh-action-pypi-publish` uploads as a direct step of that job (see `templates/publish.yml`).

Rehearse before the first tag in a repository: `publish.yml` takes a `workflow_dispatch` with a tag input and its publish steps are gated on a real tag push, so a dispatch verifies the whole chain and publishes nothing. The tag need not exist yet — that is the point — so a rehearsal binds the build to the release **branch** head instead, which catches the same "something was not built" failure.

Release candidates: `release/X.Y.Z-rcN` builds and tags exactly like a final release, but crates.io and PyPI are used **only when the manifest version is exactly the tag version**. A candidate whose manifests still carry `X.Y.Z` gets a GitHub pre-release with all its artifacts and no registry upload, because publishing `X.Y.Z` from a candidate would consume the immutable version the final release needs. **Re-point the PyPI and crates.io Trusted Publishers to `publish.yml` first** — they match on workflow filename, and a rehearsal cannot catch a stale one because it skips the upload.

Do not tag by hand. Org rulesets in `.github/rulesets/` enforce `ci-gate` on migrated repos and restrict `v*` tag creation. Org admins may merge their own PRs without a human approval; other authors still need a review. `ci-gate` is required for everyone.

## Applying org settings

```bash
gh auth refresh -h github.com -s admin:org
bash .github/rulesets/apply.sh
```

Runner group visibility and public-repository access are declared in `.github/rulesets/runners.json` and applied with `.github/scripts/apply_runners.py` (`--dry-run` first) — no runner names live in either. Boards are provisioned and labelled by `.github/scripts/provision_runner.sh`, which derives labels from the board's own name at registration time rather than from a committed spec. Machines are registered as services with `svc.sh`; the fleet's actual composition and the non-board install procedure live in Confluence.

Set organisation Copilot custom instructions to `.github/copilot-instructions.md`.
