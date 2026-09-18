#!/usr/bin/env python3
"""Fail when a workflow references an action by anything but a full commit SHA.

A tag or branch reference is mutable: `@v4` and `@master` resolve to whatever
the upstream owner last pushed, so a changed -- or compromised -- action runs
with the repository's token and secrets with no change here to review.
Dependabot updates SHA pins, so pinning costs nothing in maintenance.

Reusable workflow `uses:` lines are held to the same rule. A
`EdgeFirstAI/.github/...@main` caller is the same mutable reference, and it
silently changes which CI a repository runs.

Local references (`./path`, `.ef-ci/...`) are skipped: a local action lives in
the same reviewed commit as the workflow calling it.

A `docker://` reference is held to the same standard by its own rule. It is not
exempt -- `uses: docker://vendor/image:latest` pulls whatever that tag points at
today and runs it with the repository's token -- but a registry image is
immutable by digest rather than by git SHA, so it must carry `@sha256:<64 hex>`.

Usage: check_action_pins.py [root ...]   (default: .github)
"""

import pathlib
import re
import sys

USES = re.compile(r"^\s*-?\s*uses:\s*(.+)$")
SHA = re.compile(r"^[0-9a-fA-F]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def scan(roots: list[pathlib.Path]) -> list[str]:
    fails: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.yml")) + sorted(root.rglob("*.yaml")):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                match = USES.match(line)
                if not match:
                    continue
                ref = match.group(1).split("#", 1)[0].strip().strip("'\"")
                if ref.startswith(("./", ".ef-ci/")):
                    continue
                if ref.startswith("docker://"):
                    # Registry images pin by manifest digest, not by git SHA.
                    digest = ref.rsplit("@", 1)[-1] if "@" in ref else ""
                    if not DIGEST.fullmatch(digest):
                        fails.append(
                            f"{path}:{lineno}: docker image not pinned by digest: {line.strip()}"
                        )
                    continue
                if "@" not in ref:
                    fails.append(f"{path}:{lineno}: missing pin: {line.strip()}")
                    continue
                if not SHA.fullmatch(ref.rsplit("@", 1)[-1]):
                    fails.append(f"{path}:{lineno}: unpinned: {line.strip()}")
    return fails


def main() -> int:
    roots = [pathlib.Path(a) for a in sys.argv[1:]] or [pathlib.Path(".github")]
    fails = scan(roots)
    if fails:
        print("Third-party and reusable workflow refs must be 40-character SHAs:")
        for item in fails:
            print(f"  {item}")
        print()
        print("A tag or branch is mutable and runs unreviewed code with this")
        print("repository's token. Pin the SHA and record the version in a comment;")
        print("Dependabot will bump it.")
        return 1
    scanned = ", ".join(str(r) for r in roots)
    print(f"all scanned uses: refs are SHA-pinned ({scanned})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
