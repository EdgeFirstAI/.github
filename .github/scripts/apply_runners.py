#!/usr/bin/env python3
"""Converge the organisation's runner group settings (visibility and
allows_public_repositories) onto .github/rulesets/runners.json.

This repository is EdgeFirstAI/.github, which is public. runners.json
therefore declares only group-level settings -- category configuration that
names no machine. It used to also declare each runner's custom labels and
group membership, keyed by runner name, which made this file (and this
script) a de facto inventory of the internal board farm. That inventory
served one purpose: recovering a runner's identity after it was reflashed
and came back label-less, by re-asserting a declared spec. The identity is
now derived instead of declared -- .github/scripts/provision_runner.sh
computes a board's labels from its own registered name at provisioning
time (family/identity/equipment, per the convention in Confluence's "CICD
Pipelines" space) and applies them straight to the API, and it re-runs
cleanly on a reflashed board without consulting any file. Any other
runner's labels are a one-time `gh api` call made when that machine is set
up, for the same reason: a stable machine's labels do not drift on their
own, so there is nothing here for a converger to protect against.

What remains a converger's job is genuinely different in kind: a group's
visibility or allows_public_repositories can be changed by hand through the
web UI, silently, at any time, with no local event to prompt someone to
notice or fix it. That is real, ongoing drift with no name attached to it,
so it still belongs in a declarative, reconciled file.

Requires: gh with admin:org (gh auth refresh -h github.com -s admin:org)

Usage:
  apply_runners.py --dry-run   # print what would change; touch nothing
  apply_runners.py             # apply
  apply_runners.py --self-test # run the fixture-backed test suite
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional, Protocol

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_SPEC_PATH = HERE.parent / "rulesets" / "runners.json"


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupSpec:
    name: str
    id: int
    visibility: str
    allows_public: bool


@dataclass(frozen=True)
class Spec:
    org: str
    groups: dict[str, GroupSpec]

    @classmethod
    def load(cls, path: pathlib.Path) -> "Spec":
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = {}
        for name, g in data["groups"].items():
            groups[name] = GroupSpec(
                name=name,
                id=g["id"],
                visibility=g["visibility"],
                allows_public=g["allows_public_repositories"],
            )
        return cls(org=data["org"], groups=groups)


# --------------------------------------------------------------------------
# Operations -- concrete, inspectable, and each able to apply itself
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SetGroupSettings:
    group: str
    group_id: int
    visibility: str
    allows_public: bool


@dataclass(frozen=True)
class AccessReport:
    group: str
    group_id: int
    visibility_ok: bool
    public_ok: bool
    ops: list[SetGroupSettings]


@dataclass(frozen=True)
class PlanResult:
    errors: list[str]
    access_reports: list[AccessReport] = field(default_factory=list)

    def all_ops(self) -> list[SetGroupSettings]:
        ops: list[SetGroupSettings] = []
        for r in self.access_reports:
            ops.extend(r.ops)
        return ops


# --------------------------------------------------------------------------
# GitHub client protocol. build_plan() only calls the read method below, so
# a self-test fixture never has to implement the mutating half.
# --------------------------------------------------------------------------


class GitHubReader(Protocol):
    def group_settings(self, group_id: int) -> tuple[str, bool]: ...


class GitHub:
    """Talks to the live organisation through `gh api`, reusing the
    existing `gh auth` session rather than handling a token directly."""

    def __init__(self, org: str):
        self.org = org

    def _run(self, args: list[str], input_text: Optional[str] = None) -> str:
        result = subprocess.run(
            ["gh", "api", *args],
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def group_settings(self, group_id: int) -> tuple[str, bool]:
        out = self._run(
            [
                f"orgs/{self.org}/actions/runner-groups/{group_id}",
                "--jq",
                "[.visibility, .allows_public_repositories]",
            ]
        )
        visibility, allows_public = json.loads(out)
        return visibility, allows_public

    def set_group_settings(
        self, group_id: int, name: str, visibility: str, allows_public: bool
    ) -> None:
        # Every managed field is sent on each PATCH. `name` is documented as
        # required, and a partial body would rely on undocumented
        # leave-unchanged behaviour for whatever it omits -- on a call that
        # mutates the organisation.
        payload = json.dumps(
            {
                "name": name,
                "visibility": visibility,
                "allows_public_repositories": allows_public,
            }
        )
        self._run(
            [
                "--method",
                "PATCH",
                f"orgs/{self.org}/actions/runner-groups/{group_id}",
                "--input",
                "-",
            ],
            input_text=payload,
        )


# --------------------------------------------------------------------------
# Pure planning functions. Each takes already-fetched state and returns
# operations; none of them touch the network, which is what makes them
# self-testable with fixtures.
# --------------------------------------------------------------------------


def plan_access(
    group: GroupSpec, live_visibility: str, live_allows_public: bool
) -> AccessReport:
    visibility_ok = group.visibility == live_visibility
    public_ok = group.allows_public == live_allows_public

    # Both fields share one PATCH, so either one drifting re-sends both.
    ops: list[SetGroupSettings] = []
    if not (visibility_ok and public_ok):
        ops.append(
            SetGroupSettings(
                group=group.name,
                group_id=group.id,
                visibility=group.visibility,
                allows_public=group.allows_public,
            )
        )
    return AccessReport(
        group=group.name,
        group_id=group.id,
        visibility_ok=visibility_ok,
        public_ok=public_ok,
        ops=ops,
    )


def build_plan(spec: Spec, client: GitHubReader) -> PlanResult:
    """Fetches live state through `client` and returns the full plan."""
    access_reports: list[AccessReport] = []
    for group in spec.groups.values():
        live_visibility, live_allows_public = client.group_settings(group.id)
        access_reports.append(plan_access(group, live_visibility, live_allows_public))

    return PlanResult(errors=[], access_reports=access_reports)


# --------------------------------------------------------------------------
# Printing and execution. Kept separate from planning so the self-test never
# has to parse or match against printed text.
# --------------------------------------------------------------------------


def _say(msg: str) -> None:
    print(f"==> {msg}")


def _format_op(op: SetGroupSettings, dry_run: bool) -> str:
    verb = "would" if dry_run else "did"
    return (
        f"    {verb}: PATCH {op.group} ({op.group_id}) "
        f"visibility <- {op.visibility}, "
        f"allows_public_repositories <- {str(op.allows_public).lower()}"
    )


def print_plan(result: PlanResult, dry_run: bool) -> None:
    _say("group visibility and public-repository access")
    for r in result.access_reports:
        if not r.ops:
            print(f"    ok: {r.group} visibility and public access already correct")
            continue
        if not r.visibility_ok:
            _say(f"{r.group} ({r.group_id}) visibility has drifted")
        if not r.public_ok:
            _say(f"{r.group} ({r.group_id}) public-repository access has drifted")
        for op in r.ops:
            print(_format_op(op, dry_run))

    _say("done")


def apply_plan(result: PlanResult, client: GitHub) -> None:
    for r in result.access_reports:
        for op in r.ops:
            client.set_group_settings(op.group_id, op.group, op.visibility, op.allows_public)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would change; touch nothing."
    )
    parser.add_argument(
        "--self-test", action="store_true", help="Run the fixture-backed test suite and exit."
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    spec = Spec.load(DEFAULT_SPEC_PATH)
    client = GitHub(spec.org)
    result = build_plan(spec, client)

    print_plan(result, dry_run=args.dry_run)
    if not args.dry_run:
        apply_plan(result, client)
    return 0


# --------------------------------------------------------------------------
# Self-test. Runs against fixtures: no gh, no network, no credentials, so it
# belongs in CI next to resolve_lanes.py --self-test.
# --------------------------------------------------------------------------


class FakeGitHub:
    """Implements exactly the read method build_plan() calls, backed by
    dicts supplied by each test case. No mutating method is implemented,
    since a clean self-test run never calls apply_plan()."""

    def __init__(
        self,
        *,
        group_visibility: Optional[dict[int, str]] = None,
        group_allows_public: Optional[dict[int, bool]] = None,
    ):
        self._group_visibility = group_visibility or {}
        self._group_allows_public = group_allows_public or {}

    def group_settings(self, group_id: int) -> tuple[str, bool]:
        return (
            self._group_visibility.get(group_id, "all"),
            self._group_allows_public.get(group_id, True),
        )


def _self_test() -> int:
    failures: list[str] = []

    def check(label: str, got, want) -> None:
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # A group narrowed to `selected` in the web UI is drift: whatever
    # repository list it inherited now excludes everything absent from it.
    gpu = GroupSpec(name="gpu-cuda", id=5, visibility="all", allows_public=True)
    access = plan_access(gpu, live_visibility="selected", live_allows_public=True)
    check("visibility drift detected", len(access.ops), 1)
    check("visibility drift op type", type(access.ops[0]).__name__, "SetGroupSettings")
    check("visibility drift target", access.ops[0].visibility, "all")

    # allows_public_repositories flipped off strands every public consumer,
    # so it is drift on its own even while visibility is still correct.
    access = plan_access(gpu, live_visibility="all", live_allows_public=False)
    check("public access drift detected", len(access.ops), 1)
    check("public access drift reported", access.public_ok, False)
    check("public access drift leaves visibility ok", access.visibility_ok, True)
    check("public access drift target", access.ops[0].allows_public, True)
    # One drifted field re-sends both, since they share a single PATCH.
    check("drifted PATCH carries visibility too", access.ops[0].visibility, "all")

    access = plan_access(gpu, live_visibility="all", live_allows_public=True)
    check("converged access: no ops", access.ops, [])
    check("converged access: visibility_ok", access.visibility_ok, True)
    check("converged access: public_ok", access.public_ok, True)

    # A fully converged spec produces zero operations across every group.
    spec = Spec(
        org="EdgeFirstAI",
        groups={"gpu-cuda": GroupSpec("gpu-cuda", 5, "all", True)},
    )
    client = FakeGitHub(group_visibility={5: "all"}, group_allows_public={5: True})
    result = build_plan(spec, client)
    check("converged spec: no errors", result.errors, [])
    check("converged spec: zero ops", result.all_ops(), [])

    # A spec with one drifted group reports exactly that group's op.
    spec_drifted = Spec(
        org="EdgeFirstAI",
        groups={"gpu-cuda": GroupSpec("gpu-cuda", 5, "all", True)},
    )
    client_drifted = FakeGitHub(group_visibility={5: "selected"}, group_allows_public={5: True})
    result = build_plan(spec_drifted, client_drifted)
    check("drifted spec: no errors", result.errors, [])
    check("drifted spec: one op", len(result.all_ops()), 1)

    # --- CLI argument handling -------------------------------------------

    parser = build_parser()
    try:
        parser.parse_args(["--bogus"])
        failures.append("unknown argument: parse_args did not raise")
    except SystemExit as exc:
        check("unknown argument exits non-zero", exc.code != 0, True)

    args = parser.parse_args(["--dry-run"])
    check("--dry-run parses", args.dry_run, True)
    args = parser.parse_args(["--self-test"])
    check("--self-test parses", args.self_test, True)

    # --- The real spec file still loads -----------------------------------

    try:
        real_spec = Spec.load(DEFAULT_SPEC_PATH)
        check("real spec: has groups", len(real_spec.groups) > 0, True)
    except FileNotFoundError:
        failures.append(f"real spec: {DEFAULT_SPEC_PATH} not found")

    for f in failures:
        print(f"FAIL {f}", file=sys.stderr)
    print(f"apply_runners self-test: {len(failures)} failure(s)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
