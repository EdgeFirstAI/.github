# Security Policy

This is the default security policy for EdgeFirstAI repositories. A repository
that ships its own `SECURITY.md` supersedes it entirely — this file applies to
the repositories that do not.

## Supported Versions

Security fixes land on the current release line. Most EdgeFirstAI projects are
pre-1.0, so a fix ships in the next release of the `0.x` line rather than being
backported; upgrade to the latest release to pick it up.

A repository with a different policy — a maintenance line, a supported LTS —
says so in its own `SECURITY.md`, which replaces this file.

## Reporting a Vulnerability

**Do not open a public issue for a security report.**

Use either channel:

- **GitHub private reporting** — open the repository's **Security** tab and
  choose *Report a vulnerability*. This is the preferred route: it keeps the
  report attached to the repository it concerns and stays private until an
  advisory is published.
- **Email** — `support@au-zone.com`, with `Security Vulnerability` and the
  repository name in the subject.

Please include:

- a description of the issue and why you believe it is a security problem
- steps to reproduce, or a proof of concept
- the versions affected, and the platform if it is platform-specific
- any mitigation you are aware of

## What to Expect

1. **Acknowledgement** within **48 hours** of the report.
2. **Initial assessment** within **7 business days**.
3. **A fix timeline** set by severity:
   - **Critical** — 7 days
   - **High** — 30 days
   - **Medium** — next minor release
   - **Low** — scheduled into a future release, and we will tell you which

Once a report is received we confirm receipt and investigate, assess severity
using CVSS, develop and test a fix, coordinate disclosure timing with you,
release the fix and publish an advisory.

## Responsible Disclosure

We ask that you:

- allow reasonable time to fix the issue before disclosing it publicly
- avoid public disclosure until a patch and advisory are released
- do not exploit the vulnerability beyond what is needed to verify it
- act in good faith toward users and the security community

We commit to:

- acknowledge your report promptly
- keep you informed through remediation
- credit you in the advisory, unless you would rather remain anonymous
- work with you to understand and resolve the issue

## How Fixes Are Published

- **GitHub Security Advisories** on the affected repository
- **Release notes**, in that repository's `CHANGELOG.md`
- **Package registries** — a new version on crates.io, PyPI or the relevant
  registry, depending on what the repository ships

To be notified, watch the repository for security advisories and follow its
releases.

## Dependencies

A Rust repository on the shared pipelines runs `cargo audit` nightly against
the RustSec advisory database, ungated, so a new advisory is reported against
an unchanged tree rather than waiting for the next commit. Those repositories
also check dependency and licence policy on every pull request, and produce a
full SBOM for each release built through the shared release workflow.

Repositories on the Python or CMake pipelines, or on none, do not get those
lanes from this policy — what they run is in their own workflows. The reporting
route below applies to every repository either way.

A vulnerability in a third-party dependency is best reported upstream first;
tell us as well if an EdgeFirstAI project needs to respond to it.
