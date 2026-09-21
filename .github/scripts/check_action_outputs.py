#!/usr/bin/env python3
"""Assert that every composite action output a caller reads is declared.

A composite action's steps write to `$GITHUB_OUTPUT` like any other step, but
those writes are scoped to the action. At the call site,
`steps.<id>.outputs.<key>` resolves against the action's own `outputs:` block,
not against what its inner steps wrote. A key missing from that block is not an
error: it evaluates to the empty string.

That is the whole problem. A lane guarded by `if: ... == 'true'` silently stops
running, a matrix silently becomes empty, and the workflow reports success. The
failure has no message and no failed step, so nothing except reading the two
files together finds it.

Both spellings of a same-repository reference are checked, `$/.github/actions/x`
and `./.github/actions/x`. A reference to another repository's action is
skipped: its definition is not here to check against.

Usage: check_action_outputs.py [roots...]    (default: .github)
       check_action_outputs.py --self-test
"""

import pathlib
import re
import sys

import yaml

USES = re.compile(r"^(?:\$/|\./)(\.github/actions/[^@\s]+?)/?$")


def declared_outputs(action_dir):
    """The output names an action declares, or None if it has no definition."""
    for name in ("action.yml", "action.yaml"):
        path = pathlib.Path(action_dir) / name
        if path.is_file():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return set((loaded.get("outputs") or {}).keys())
    return None


def local_action(uses):
    """The repository-relative action directory for a same-repo `uses:`."""
    if not isinstance(uses, str):
        return None
    match = USES.match(uses.strip())
    return match.group(1) if match else None


def step_ids(job):
    """Map each step id to the same-repository action directory it calls."""
    found = {}
    for step in job.get("steps") or []:
        if not isinstance(step, dict) or not step.get("id"):
            continue
        action = local_action(step.get("uses", ""))
        if action:
            found[step["id"]] = action
    return found


def check_workflow(path, resolve=declared_outputs):
    """Return a list of complaints about one workflow file."""
    text = pathlib.Path(path).read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [f"{path}: cannot parse: {exc}"]

    problems = []
    for job_name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step_id, action in step_ids(job).items():
            outputs = resolve(action)
            if outputs is None:
                continue
            pattern = re.compile(
                r"steps\.%s\.outputs\.([A-Za-z0-9_-]+)" % re.escape(step_id)
            )
            for key in sorted(set(pattern.findall(text))):
                if key not in outputs:
                    problems.append(
                        f"{path}: job '{job_name}' reads "
                        f"steps.{step_id}.outputs.{key}, but {action}/action.yml "
                        f"declares no such output -- it will be the empty string"
                    )
    return problems


def main(argv):
    roots = argv or [".github"]
    files = []
    for root in roots:
        base = pathlib.Path(root)
        for pattern in ("*.yml", "*.yaml"):
            files.extend(sorted(base.rglob(pattern)))

    problems = []
    for path in files:
        # An action file can call another action, but it cannot declare jobs;
        # only workflows have the call sites this checks.
        if path.name in ("action.yml", "action.yaml"):
            continue
        problems.extend(check_workflow(path))

    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    if problems:
        print(f"{len(problems)} undeclared composite output(s)", file=sys.stderr)
        return 1
    print(f"composite outputs: {len(files)} file(s) checked, all declared")
    return 0


def _self_test():
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    check("bare $/", local_action("$/.github/actions/resolve-lanes"),
          ".github/actions/resolve-lanes")
    check("dot-slash", local_action("./.github/actions/setup-rust"),
          ".github/actions/setup-rust")
    check("trailing slash", local_action("$/.github/actions/wheel-data/"),
          ".github/actions/wheel-data")
    # A remote action's definition is not in this tree to check against.
    check("remote pinned", local_action("actions/checkout@abc123"), None)
    check("remote path", local_action("EdgeFirstAI/.github/.github/actions/x@sha"), None)
    check("empty", local_action(""), None)
    check("not a string", local_action(None), None)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        workflow = root / "w.yml"
        workflow.write_text(
            "jobs:\n"
            "  setup:\n"
            "    outputs:\n"
            "      a: ${{ steps.map.outputs.declared }}\n"
            "      b: ${{ steps.map.outputs.missing }}\n"
            "      c: ${{ steps.own.outputs.anything }}\n"
            "    steps:\n"
            "      - id: own\n"
            "        run: echo anything=1 >> $GITHUB_OUTPUT\n"
            "      - id: map\n"
            "        uses: $/.github/actions/resolve-lanes\n"
            "      - id: ext\n"
            "        uses: actions/checkout@abc\n",
            encoding="utf-8",
        )
        found = check_workflow(workflow, resolve=lambda a: {"declared"})
        check("one complaint", len(found), 1)
        check("names the missing key", "outputs.missing" in found[0], True)
        # A plain `run:` step's outputs are job-scoped and always readable.
        check("own step not flagged", "steps.own" in " ".join(found), False)

        # An action with no definition on disk cannot be judged.
        check("unresolvable action skipped",
              check_workflow(workflow, resolve=lambda a: None), [])

        # The real failure mode: an action declaring nothing at all.
        every = check_workflow(workflow, resolve=lambda a: set())
        check("both keys flagged when outputs absent", len(every), 2)

    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    print(f"check_action_outputs self-test: {len(failures)} failure(s)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main(sys.argv[1:]))
