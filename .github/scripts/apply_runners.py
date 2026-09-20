#!/usr/bin/env python3
"""Converge the organisation's runner groups, group visibility and custom labels
onto .github/rulesets/runners.json.

Ported from apply-runners.sh. The bash version could only add: it POSTed
missing labels, PUT the access list when it drifted, and PUT missing group
members, but never removed anything the spec no longer declared. That is a
one-directional converger, not a reconciler, and it took four separate fix
rounds to reach even that -- each one impossible to regress-test in bash.
This port makes every phase authoritative in both directions and adds a
--self-test that runs against fixtures, with no credentials and no network
access, so CI can run it the way it runs resolve_lanes.py.

Phases, in order, and why the order matters:

  A. Custom labels     -- adds what a runner's declared list is missing and
                           removes custom labels it has that are not
                           declared. Only type: custom labels are ever
                           touched; GitHub's auto-assigned labels are
                           filtered out explicitly here rather than relied
                           on the API to reject removing one. Removals run
                           before additions for the same runner: GitHub
                           label identity is case-insensitive, so adding a
                           label that differs only in case from one already
                           present is a silent no-op, and an add-then-delete
                           would delete the only copy that exists. A runner
                           absent from .labels is unmanaged -- its labels
                           are not touched at all. A runner declared with an
                           empty list is refused outright, since applying it
                           would strip every custom label the runner has.

  B. Group visibility   -- every managed group is `all`, reachable by every
                           repository in the organisation. Groups are an
                           organisational seam, not an access boundary, so
                           no per-repository list is declared or reconciled.
                           What keeps untrusted code off these machines is
                           the trusted-event guard in resolve_lanes.py,
                           which runs per workflow run; a group's repository
                           list cannot distinguish a fork's pull request
                           from the base repository's own push and so never
                           provided that guarantee. Visibility is still
                           reconciled, because a group narrowed to
                           `selected` in the web UI would silently strand
                           every repository absent from the list it
                           inherited.

  C. Group membership   -- adds a declared runner that is missing from its
                           group. A runner that is a member of a managed
                           group but not declared for it is a policy
                           question, not a bug this script can resolve: the
                           only obvious destination is Default, the
                           broadly-reachable group this whole design exists
                           to empty, so moving it there automatically would
                           be the worst possible default. It is reported as
                           a hard error naming the runner and the group
                           instead.

Every organisation runner group except the built-in Default is declared in
.groups. A group absent from it is not managed here at all, which is a
state worth avoiding: an undeclared group is exactly where drift hides.

Usage:
  apply_runners.py --dry-run   # print what would change; touch nothing
  apply_runners.py             # apply
  apply_runners.py --self-test # run the fixture-backed test suite

Requires: gh with admin:org (gh auth refresh -h github.com -s admin:org)
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
class LabelInfo:
    name: str
    type: str  # "custom" or "read-only", exactly as GitHub reports it


@dataclass(frozen=True)
class GroupSpec:
    name: str
    id: int
    visibility: str
    runners: list[str]


@dataclass(frozen=True)
class Spec:
    org: str
    groups: dict[str, GroupSpec]
    labels: dict[str, list[str]]

    @classmethod
    def load(cls, path: pathlib.Path) -> "Spec":
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = {}
        for name, g in data["groups"].items():
            groups[name] = GroupSpec(
                name=name,
                id=g["id"],
                visibility=g["visibility"],
                runners=list(g.get("runners", [])),
            )
        return cls(org=data["org"], groups=groups, labels=dict(data.get("labels", {})))


def validate_spec(spec: Spec) -> list[str]:
    """Config-only checks: no network access, so these run before anything
    reaches the API. An empty declared label list is refused here, since
    applying it would strip every custom label the named runner has, and
    that is far more likely a mistake than an intention."""
    errors = []
    for name, labels in spec.labels.items():
        if not labels:
            errors.append(
                f"runner '{name}' declares an empty label list in runners.json -- "
                "refusing, since applying it would strip every custom label the "
                "runner has. Remove the runner from .labels instead if its labels "
                "are meant to be unmanaged."
            )
    return errors


# --------------------------------------------------------------------------
# Operations -- concrete, inspectable, and each able to apply itself
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AddLabel:
    runner: str
    runner_id: int
    label: str


@dataclass(frozen=True)
class RemoveLabel:
    runner: str
    runner_id: int
    label: str


@dataclass(frozen=True)
class SetVisibility:
    group: str
    group_id: int
    visibility: str


@dataclass(frozen=True)
class AddMember:
    group: str
    group_id: int
    runner: str
    runner_id: int


Op = AddLabel | RemoveLabel | SetVisibility | AddMember


# --------------------------------------------------------------------------
# Per-phase reports -- ops plus enough context to print "ok" lines for the
# parts that already match, without recomputing the comparison twice.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelReport:
    runner: str
    runner_id: int
    kept: list[str]
    ops: list[Op]


@dataclass(frozen=True)
class AccessReport:
    group: str
    group_id: int
    visibility_ok: bool
    ops: list[Op]


@dataclass(frozen=True)
class MembershipReport:
    group: str
    group_id: int
    kept: list[str]
    ops: list[Op]


@dataclass(frozen=True)
class PlanResult:
    errors: list[str]
    label_reports: list[LabelReport] = field(default_factory=list)
    access_reports: list[AccessReport] = field(default_factory=list)
    membership_reports: list[MembershipReport] = field(default_factory=list)

    def all_ops(self) -> list[Op]:
        ops: list[Op] = []
        for r in self.label_reports:
            ops.extend(r.ops)
        for r in self.access_reports:
            ops.extend(r.ops)
        for r in self.membership_reports:
            ops.extend(r.ops)
        return ops


# --------------------------------------------------------------------------
# GitHub client protocol. build_plan() only calls the read methods below, so
# a self-test fixture never has to implement the mutating half.
# --------------------------------------------------------------------------


class GitHubReader(Protocol):
    def runner_id(self, name: str) -> Optional[int]: ...
    def runner_labels(self, runner_id: int) -> list[LabelInfo]: ...
    def group_visibility(self, group_id: int) -> str: ...
    def group_members(self, group_id: int) -> list[dict]: ...


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

    def runner_id(self, name: str) -> Optional[int]:
        out = self._run(
            [
                f"orgs/{self.org}/actions/runners",
                "--paginate",
                "--jq",
                f'.runners[] | select(.name=="{name}") | .id',
            ]
        ).strip()
        return int(out) if out else None

    def runner_labels(self, runner_id: int) -> list[LabelInfo]:
        out = self._run(
            [
                f"orgs/{self.org}/actions/runners/{runner_id}",
                "--jq",
                "[.labels[] | {name: .name, type: .type}]",
            ]
        )
        return [LabelInfo(name=d["name"], type=d["type"]) for d in json.loads(out)]

    def add_label(self, runner_id: int, label: str) -> None:
        self._run(
            [
                "--method",
                "POST",
                f"orgs/{self.org}/actions/runners/{runner_id}/labels",
                "-f",
                f"labels[]={label}",
            ]
        )

    def remove_label(self, runner_id: int, label: str) -> None:
        self._run(
            [
                "--method",
                "DELETE",
                f"orgs/{self.org}/actions/runners/{runner_id}/labels/{label}",
            ]
        )

    def group_visibility(self, group_id: int) -> str:
        return self._run(
            [f"orgs/{self.org}/actions/runner-groups/{group_id}", "--jq", ".visibility"]
        ).strip()

    def set_group_visibility(self, group_id: int, name: str, visibility: str) -> None:
        # `name` is documented as required on this PATCH even though only
        # visibility is changing; omitting it risks relying on undocumented
        # leave-unchanged behaviour on a call that mutates the organisation.
        payload = json.dumps({"name": name, "visibility": visibility})
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

    def group_members(self, group_id: int) -> list[dict]:
        out = self._run(
            [
                f"orgs/{self.org}/actions/runner-groups/{group_id}/runners",
                "--jq",
                "[.runners[] | {id: .id, name: .name}]",
            ]
        )
        return json.loads(out)

    def add_member(self, group_id: int, runner_id: int) -> None:
        self._run(
            [
                "--method",
                "PUT",
                f"orgs/{self.org}/actions/runner-groups/{group_id}/runners/{runner_id}",
            ]
        )


# --------------------------------------------------------------------------
# Pure planning functions. Each takes already-fetched state and returns
# operations; none of them touch the network, which is what makes them
# self-testable with fixtures.
# --------------------------------------------------------------------------


def plan_labels(
    runner: str, runner_id: int, declared: list[str], current: list[LabelInfo]
) -> LabelReport:
    custom_names = {l.name for l in current if l.type == "custom"}
    declared_set = set(declared)

    kept = [name for name in declared if name in custom_names]
    # Sorted for a deterministic dry-run; today's fleet never declares more
    # than one removal per runner; this simply avoids the alternative of an
    # arbitrary set-iteration order once one does.
    removals = sorted(custom_names - declared_set)
    additions = [name for name in declared if name not in custom_names]

    ops: list[Op] = [RemoveLabel(runner, runner_id, l) for l in removals]
    ops += [AddLabel(runner, runner_id, l) for l in additions]
    return LabelReport(runner=runner, runner_id=runner_id, kept=kept, ops=ops)


def plan_access(group: GroupSpec, live_visibility: str) -> AccessReport:
    visibility_ok = group.visibility == live_visibility
    ops: list[Op] = []
    if not visibility_ok:
        ops.append(
            SetVisibility(group=group.name, group_id=group.id, visibility=group.visibility)
        )
    return AccessReport(
        group=group.name,
        group_id=group.id,
        visibility_ok=visibility_ok,
        ops=ops,
    )


class UndeclaredMemberError(Exception):
    def __init__(self, group: str, runner: str):
        super().__init__(
            f"runner '{runner}' is a member of managed group '{group}' but is not "
            "declared for it in runners.json -- refusing to move it. Add it to the "
            "group's runners list if it belongs there, or remove it from the group "
            "by hand if it does not."
        )
        self.group = group
        self.runner = runner


def plan_membership(
    group: GroupSpec, runner_ids: dict[str, int], live_members: list[dict]
) -> tuple[MembershipReport, list[UndeclaredMemberError]]:
    live_names = {m["name"] for m in live_members}
    declared_names = set(group.runners)

    kept = [name for name in group.runners if name in live_names]
    ops: list[Op] = [
        AddMember(group=group.name, group_id=group.id, runner=name, runner_id=runner_ids[name])
        for name in group.runners
        if name not in live_names
    ]
    errors = [
        UndeclaredMemberError(group.name, name)
        for name in sorted(live_names - declared_names)
    ]
    return (
        MembershipReport(group=group.name, group_id=group.id, kept=kept, ops=ops),
        errors,
    )


def build_plan(spec: Spec, client: GitHubReader) -> PlanResult:
    """Fetches live state through `client` and returns the full plan. Any
    runner named in the spec (in .labels or in a group's .runners) that the
    organisation does not have, and any undeclared member of a managed
    group, is collected as an error. If there is any error at all, the
    caller must not apply anything -- not even the operations for the parts
    that were clean -- so a stale runner or a config mistake never lets
    part of a converge happen silently."""
    errors: list[str] = []
    runner_id_cache: dict[str, Optional[int]] = {}

    def resolve_runner(name: str) -> Optional[int]:
        if name not in runner_id_cache:
            runner_id_cache[name] = client.runner_id(name)
            if runner_id_cache[name] is None:
                errors.append(f"runner '{name}' not found in {spec.org}")
        return runner_id_cache[name]

    label_reports: list[LabelReport] = []
    for name, declared in spec.labels.items():
        runner_id = resolve_runner(name)
        if runner_id is None:
            continue
        current = client.runner_labels(runner_id)
        label_reports.append(plan_labels(name, runner_id, declared, current))

    access_reports: list[AccessReport] = []
    for group in spec.groups.values():
        access_reports.append(plan_access(group, client.group_visibility(group.id)))

    membership_reports: list[MembershipReport] = []
    for group in spec.groups.values():
        runner_ids: dict[str, int] = {}
        skip_group = False
        for name in group.runners:
            rid = resolve_runner(name)
            if rid is None:
                skip_group = True
                continue
            runner_ids[name] = rid
        if skip_group:
            continue
        live_members = client.group_members(group.id)
        report, member_errors = plan_membership(group, runner_ids, live_members)
        membership_reports.append(report)
        errors.extend(str(e) for e in member_errors)

    return PlanResult(
        errors=errors,
        label_reports=label_reports,
        access_reports=access_reports,
        membership_reports=membership_reports,
    )


# --------------------------------------------------------------------------
# Printing and execution. Kept separate from planning so the self-test never
# has to parse or match against printed text.
# --------------------------------------------------------------------------


def _say(msg: str) -> None:
    print(f"==> {msg}")


def _format_op(op: Op, dry_run: bool) -> str:
    verb = "would" if dry_run else "did"
    if isinstance(op, RemoveLabel):
        prefix = f"    {'would remove' if dry_run else 'removed'}"
        return f"{prefix}: DELETE label '{op.label}' from {op.runner} ({op.runner_id})"
    if isinstance(op, AddLabel):
        return f"    {verb}: POST label '{op.label}' to {op.runner} ({op.runner_id})"
    if isinstance(op, SetVisibility):
        return f"    {verb}: PATCH {op.group} ({op.group_id}) visibility <- {op.visibility}"
    if isinstance(op, AddMember):
        return f"    {verb}: PUT {op.runner} ({op.runner_id}) into {op.group} ({op.group_id})"
    raise TypeError(f"unhandled op type: {type(op)!r}")


def print_plan(result: PlanResult, dry_run: bool) -> None:
    _say("Phase A: custom labels")
    for r in result.label_reports:
        for label in r.kept:
            print(f"    ok: {r.runner} already has {label}")
        # Removals precede additions in the plan already; print them in that
        # order too, so a reader skimming --dry-run output sees the rename
        # sequence in the order it will actually execute.
        for op in r.ops:
            if isinstance(op, RemoveLabel):
                _say(f"REMOVING label '{op.label}' from {op.runner} ({op.runner_id}) -- not declared in runners.json")
            else:
                _say(f"adding label '{op.label}' to {op.runner} ({op.runner_id})")
            print(_format_op(op, dry_run))

    _say("Phase B: group visibility")
    for r in result.access_reports:
        if not r.ops:
            print(f"    ok: {r.group} visibility already correct")
            continue
        for op in r.ops:
            _say(f"setting {op.group} ({op.group_id}) visibility to: {op.visibility}")
            print(_format_op(op, dry_run))

    _say("Phase C: group membership")
    for r in result.membership_reports:
        for name in r.kept:
            print(f"    ok: {name} already in {r.group}")
        for op in r.ops:
            assert isinstance(op, AddMember)
            _say(f"moving {op.runner} ({op.runner_id}) into {op.group} ({op.group_id})")
            print(_format_op(op, dry_run))

    _say("done")


def apply_plan(result: PlanResult, client: GitHub) -> None:
    """Applies every operation. Only called after build_plan() returned no
    errors, so a partial or stale spec never causes a partial apply."""
    for r in result.label_reports:
        for op in r.ops:
            if isinstance(op, RemoveLabel):
                client.remove_label(op.runner_id, op.label)
            elif isinstance(op, AddLabel):
                client.add_label(op.runner_id, op.label)
    for r in result.access_reports:
        for op in r.ops:
            assert isinstance(op, SetVisibility)
            client.set_group_visibility(op.group_id, op.group, op.visibility)
    for r in result.membership_reports:
        for op in r.ops:
            assert isinstance(op, AddMember)
            client.add_member(op.group_id, op.runner_id)


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
    errors = validate_spec(spec)
    if not errors:
        client = GitHub(spec.org)
        result = build_plan(spec, client)
        errors = result.errors

    if errors:
        for err in errors:
            print(f"::error::{err}", file=sys.stderr)
        return 1

    print_plan(result, dry_run=args.dry_run)
    if not args.dry_run:
        apply_plan(result, client)
    return 0


# --------------------------------------------------------------------------
# Self-test. Every case here runs against fixtures: no gh, no network, no
# credentials, so it belongs in CI next to resolve_lanes.py --self-test.
# --------------------------------------------------------------------------


class FakeGitHub:
    """Implements exactly the read methods build_plan() calls, backed by
    dicts supplied by each test case. No mutating method is implemented,
    since a clean self-test run never calls apply_plan()."""

    def __init__(
        self,
        *,
        runner_ids: Optional[dict[str, int]] = None,
        labels: Optional[dict[int, list[LabelInfo]]] = None,
        group_visibility: Optional[dict[int, str]] = None,
        group_members: Optional[dict[int, list[dict]]] = None,
    ):
        self._runner_ids = runner_ids or {}
        self._labels = labels or {}
        self._group_visibility = group_visibility or {}
        self._group_members = group_members or {}

    def runner_id(self, name: str) -> Optional[int]:
        return self._runner_ids.get(name)

    def runner_labels(self, runner_id: int) -> list[LabelInfo]:
        return self._labels.get(runner_id, [])

    def group_visibility(self, group_id: int) -> str:
        return self._group_visibility.get(group_id, "all")

    def group_members(self, group_id: int) -> list[dict]:
        return self._group_members.get(group_id, [])


def _self_test() -> int:
    failures: list[str] = []

    def check(label: str, got, want) -> None:
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # --- Phase A -----------------------------------------------------

    # Removals ordered before additions, and a case-only rename does not
    # get skipped as "already has": GitHub label identity is
    # case-insensitive, so treating CUDA as satisfying a declared cuda
    # would leave the casing mismatched forever.
    report = plan_labels(
        "mltrain-02",
        1,
        ["cuda"],
        [LabelInfo("CUDA", "custom")],
    )
    check("rename ops order", [type(o).__name__ for o in report.ops], ["RemoveLabel", "AddLabel"])
    check("rename removes old casing", report.ops[0].label, "CUDA")
    check("rename adds new casing", report.ops[1].label, "cuda")

    # Read-only labels are never candidates for removal, no matter what is
    # declared: only type == "custom" entries are compared against .labels.
    report = plan_labels(
        "mltrain-02",
        1,
        ["CUDA"],
        [LabelInfo("Linux", "read-only"), LabelInfo("CUDA", "custom")],
    )
    check("read-only never removed", report.ops, [])
    check("read-only kept as ok", report.kept, ["CUDA"])

    # A fully converged runner produces no ops.
    report = plan_labels("ubuntubuild", 2, ["build"], [LabelInfo("build", "custom")])
    check("converged labels: no ops", report.ops, [])

    # Empty declared list is refused before any network access.
    errs = validate_spec(Spec(org="EdgeFirstAI", groups={}, labels={"mltrain-02": []}))
    check("empty label list refused", len(errs), 1)
    check("empty label list names the runner", "mltrain-02" in errs[0], True)

    # --- Phase B -------------------------------------------------------

    # A group narrowed to `selected` in the web UI is drift: whatever
    # repository list it inherited now excludes everything absent from it.
    gpu = GroupSpec(name="gpu-cuda", id=5, visibility="all", runners=[])
    access = plan_access(gpu, live_visibility="selected")
    check("visibility drift detected", len(access.ops), 1)
    check("visibility drift op type", type(access.ops[0]).__name__, "SetVisibility")
    check("visibility drift target", access.ops[0].visibility, "all")

    access = plan_access(gpu, live_visibility="all")
    check("converged access: no ops", access.ops, [])
    check("converged access: visibility_ok", access.visibility_ok, True)

    # --- Phase C -------------------------------------------------------

    group = GroupSpec(name="gpu-cuda", id=5, visibility="all", runners=["mltrain-02"])
    report, errs = plan_membership(
        group,
        {"mltrain-02": 1},
        [{"id": 1, "name": "mltrain-02"}, {"id": 99, "name": "stray-runner"}],
    )
    check("undeclared member fails, not moved", len(errs), 1)
    check("undeclared member names the runner", "stray-runner" in str(errs[0]), True)
    check("undeclared member names the group", "gpu-cuda" in str(errs[0]), True)
    check("declared member still reported ok", report.kept, ["mltrain-02"])
    check("no add op for the undeclared runner", report.ops, [])

    group = GroupSpec(name="gpu-cuda", id=5, visibility="all", runners=["mltrain-02"])
    report, errs = plan_membership(group, {"mltrain-02": 1}, [])
    check("missing member is added", len(report.ops), 1)
    check("missing member op type", type(report.ops[0]).__name__, "AddMember")
    check("no membership errors when nothing is stray", errs, [])

    # --- Full converged spec: zero operations everywhere ----------------

    spec = Spec(
        org="EdgeFirstAI",
        groups={"gpu-cuda": GroupSpec("gpu-cuda", 5, "all", ["mltrain-02"])},
        labels={"mltrain-02": ["CUDA"]},
    )
    client = FakeGitHub(
        runner_ids={"mltrain-02": 1},
        labels={1: [LabelInfo("CUDA", "custom")]},
        group_visibility={5: "all"},
        group_members={5: [{"id": 1, "name": "mltrain-02"}]},
    )
    result = build_plan(spec, client)
    check("converged spec: no errors", result.errors, [])
    check("converged spec: zero ops", result.all_ops(), [])

    # A runner absent from .labels is unmanaged: build_plan() never looks
    # at it, so it produces neither an op nor an error.
    check("unmanaged runner not in label reports", [r.runner for r in result.label_reports], ["mltrain-02"])

    # A runner named in the spec that the org does not have fails loudly.
    spec_missing = Spec(
        org="EdgeFirstAI",
        groups={},
        labels={"ghost-runner": ["build"]},
    )
    result = build_plan(spec_missing, FakeGitHub())
    check("missing runner fails loudly", len(result.errors), 1)
    check("missing runner error names it", "ghost-runner" in result.errors[0], True)

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

    # --- The real spec file still loads and passes validation -----------

    try:
        real_spec = Spec.load(DEFAULT_SPEC_PATH)
        check("real spec: no validation errors", validate_spec(real_spec), [])
    except FileNotFoundError:
        failures.append(f"real spec: {DEFAULT_SPEC_PATH} not found")

    for f in failures:
        print(f"FAIL {f}", file=sys.stderr)
    print(f"apply_runners self-test: {len(failures)} failure(s)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
