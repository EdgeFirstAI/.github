# Contributing to EdgeFirstAI Projects

This is the default contributing guide for EdgeFirstAI repositories. It covers
what is the same everywhere: branches, commits, review, and how CI is
structured. A repository that ships its own `CONTRIBUTING.md` replaces it —
that file is where build commands, toolchains, hardware requirements and test
layout belong, because those differ per project.

## Code of Conduct

Participation is governed by the
[EdgeFirstAI Code of Conduct](https://github.com/EdgeFirstAI/.github/blob/main/CODE_OF_CONDUCT.md),
which applies to every repository in the organisation. Unlike this guide, it is
not a per-project default: a repository carrying its own copy is carrying a
copy, not a variation. Report a concern privately through the repository's
**Security** tab or by emailing `support@au-zone.com`.

## Before You Start

- Search existing issues and pull requests; the work may already be underway.
- For anything substantial, open an issue first. Agreeing the approach is
  cheaper than reworking a finished branch.
- Small fixes — a typo, a broken link, an obvious bug — do not need that.

## Branches

Prefix the branch with its kind, then a short slug. Ticketed work carries the
JIRA key.

- `feat/` or `feature/` — `feature/EDGEAI-1018-sahi-tiling`
- `bugfix/` or `fix/` — `bugfix/EDGEAI-1353-egl-loader-ub`
- `ci/`, `docs/`, `chore/`, `bench/` — infrastructure, documentation, measurement
- `release/X.Y.Z` — release preparation. Merging one to `main` is what creates
  the version tag, so the name is load-bearing rather than cosmetic.

## Commits

**Every commit must be DCO-signed:** `git commit -s`. A pull request with an
unsigned commit is blocked by the DCO check.

With a JIRA ticket, lead with the key:

```text
EDGEAI-123: Add tensor operation for matrix multiplication
```

Otherwise use Conventional Commits, scoped where it helps:

```text
feat(image): route planar heap destinations through the two-pass GL plan
fix(ci): stop interpolating the PR branch name into tag-release.yml
docs: reconcile the three batch memory representations
```

Write the message for someone reading it in a year without the diff: what
changed and why, not a restatement of the patch.

## Pull Requests

1. Push the branch and open a pull request against `main`.
2. `CODEOWNERS` requests review automatically.
3. Describe what changed and why, the ticket if there is one, and what you did
   to verify it — including which hardware, where that matters.
4. Add a `CHANGELOG.md` entry under `[Unreleased]` for anything user-facing.
5. Get CI green and address review feedback.

Open a draft pull request for work in progress. Draft pull requests run no CI
at all, which is the intended way to push freely on a long change.

## How CI Runs

Repositories on the shared pipelines use three tiers, and knowing which one you
are in explains what you will and will not see:

- **Quick** runs on a push to a non-draft pull request that touches code —
  format, lint, cross-target lint, host tests, dependency licence policy,
  workflow lint. It is budgeted at ten minutes. A change confined to
  documentation is filtered out by path and skips it deliberately; `ci-gate`
  still runs and reports success, so a docs-only pull request is not held up
  waiting for a job that was never going to start.
- **Full** does *not* run automatically. A reviewer adds the `ci:full` label to
  request it: the platform matrix, on-target hardware lanes, coverage and the
  full SBOM. It re-runs on later pushes while the label is present.
- **Nightly** is the safety net for anything Full skipped, plus a `cargo audit`
  that runs every night whether the code changed or not.

One check is required: **`ci-gate`**. It always runs and reports success only
when every lane that ran succeeded and every lane that did not run was skipped.

Reproduce Quick locally before pushing; each repository's own `CONTRIBUTING.md`
or `Makefile` gives the exact commands, which depend on what it builds.

## Releases

Release preparation lands on `release/X.Y.Z` and is opened as a pull request
into `main` carrying `ci:full`. A tag deploys; it never builds:

| Step | Trigger | Result |
|------|---------|--------|
| `release.yml` | push to `release/X.Y.Z` | builds every distribution artifact |
| `tag-release.yml` | that pull request merged | creates the annotated `vX.Y.Z` tag |
| `publish.yml` | the `vX.Y.Z` tag | publishes what was already built |

Be precise about what enforces this, because the merge button is not it.
`ci-gate` is the required check, and `release.yml` runs on a branch push rather
than on the pull request — so a release pull request can be merged while its
build is pending or red. What that costs is the tag: `tag-release.yml` refuses
to create one unless the build is green for the exact commit being merged, so a
merged release with a broken build leaves no tag rather than a tag whose
artifacts do not exist.

**Check the release build before merging**, and **never create a `v*` tag by
hand.**

Bring dependencies current *before* preparing a release, not after. A release
cut on stale dependencies is behind the moment it ships.

## Code Style

- Formatting and linting are enforced by CI, not by review. Run them locally
  first; a reviewer's time is better spent on what the change does.
- Match the surrounding code. A file with a consistent style is worth more than
  one that is individually perfect.
- Comment what is not obvious from the code: why a thing is done, what
  constraint forced it, what breaks if it changes. Do not narrate the diff or
  record issue history — that is what the commit message and CHANGELOG are for.
- Public API carries documentation. Anything a caller can reach should say what
  it does and what it guarantees.

## Getting Help

- Open an issue on the repository for a question about that project.
- `support@au-zone.com` for anything commercial, or anything you would rather
  not discuss in public.
- Security issues follow [SECURITY.md](https://github.com/EdgeFirstAI/.github/blob/main/SECURITY.md) — never a public issue.

## License

Contributions are made under the repository's license; see its `LICENSE` file.
Signing off a commit with `-s` certifies you have the right to submit it under
that license, per the [Developer Certificate of Origin](https://developercertificate.org/).
