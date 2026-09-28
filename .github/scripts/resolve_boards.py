#!/usr/bin/env python3
"""Resolve board entries into a job matrix for an on-demand board workflow.

`boards` uses rust-full's syntax (see `resolve_lanes.parse_boards`): comma-
separated entries, each one or more labels joined by `+`. Where rust-full
schedules every entry, a caller of this script may also pass a token that can
read the organisation's self-hosted runners. Entries no online runner can
serve are then moved to `unavailable` rather than scheduled: a job naming
labels no online runner carries waits in the queue for 24 hours before GitHub
fails it, which reads as a hung workflow rather than an absent board.

A busy runner is available; it takes the job when its current one finishes.

Configuration arrives as environment variables (BOARDS, TOKEN, ORG, EVENT,
REPO, PR_HEAD_REPO) and results are appended to $GITHUB_OUTPUT. Run with
--self-test to execute the unit tests; ci.yml does.
"""

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from resolve_lanes import LaneError, is_trusted, parse_boards  # noqa: E402

API = "https://api.github.com"


def fetch_runners(org, token):
    """Every self-hosted runner in the organisation, paginated."""
    runners = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"{API}/orgs/{org}/actions/runners?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            raise LaneError(
                f"listing {org}'s runners failed: HTTP {exc.code}; the token "
                "needs read access to organisation self-hosted runners"
            ) from exc
        except urllib.error.URLError as exc:
            raise LaneError(f"listing {org}'s runners failed: {exc.reason}") from exc
        batch = body.get("runners") or []
        runners.extend(batch)
        if len(runners) >= body.get("total_count", 0) or not batch:
            return runners
        page += 1


def split_online(entries, runners):
    """Partition entries by whether an online runner carries every label."""
    online = []
    for runner in runners:
        if runner.get("status") != "online":
            continue
        labels = {label["name"].lower() for label in runner.get("labels") or []}
        online.append((runner["name"], labels))

    available, unavailable = [], []
    for entry in entries:
        wanted = {label.lower() for label in entry["labels"]}
        names = sorted(name for name, labels in online if wanted <= labels)
        if names:
            available.append(entry)
        else:
            unavailable.append({
                "runner": entry["runner"],
                "reason": "no online runner carries "
                          + ", ".join(entry["labels"][1:]),
            })
    return available, unavailable


def resolve(env, fetch=fetch_runners):
    entries = parse_boards(env.get("BOARDS"))
    if not entries:
        raise LaneError("boards must name at least one board")

    if not is_trusted(env):
        # A fork's code must never reach self-hosted capacity.
        return {
            "board_matrix": [],
            "unavailable": [{"runner": e["runner"], "reason": "untrusted trigger"}
                            for e in entries],
            "online_checked": False,
        }

    token = (env.get("TOKEN") or "").strip()
    if not token:
        return {"board_matrix": entries, "unavailable": [], "online_checked": False}

    available, unavailable = split_online(entries, fetch(env.get("ORG"), token))
    return {"board_matrix": available, "unavailable": unavailable,
            "online_checked": True}


def _emit(result, stream):
    stream.write(f"board_matrix<<EOF\n{json.dumps(result['board_matrix'])}\nEOF\n")
    stream.write(f"unavailable<<EOF\n{json.dumps(result['unavailable'])}\nEOF\n")
    stream.write(f"has_boards={'true' if result['board_matrix'] else 'false'}\n")
    stream.write(f"online_checked={'true' if result['online_checked'] else 'false'}\n")


def main():
    try:
        result = resolve(os.environ)
    except LaneError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if not result["online_checked"] and result["board_matrix"]:
        print("::warning::no runner token, so boards were not checked for an "
              "online runner; a board no online runner serves will queue",
              file=sys.stderr)
    for gone in result["unavailable"]:
        print(f"::warning::{gone['runner']}: {gone['reason']}", file=sys.stderr)
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            _emit(result, handle)
    else:
        _emit(result, sys.stdout)
    return 0


def _self_test() -> int:
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    def check_raises(label, fn):
        try:
            fn()
        except LaneError:
            return
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: raised {type(exc).__name__}, want LaneError")
            return
        failures.append(f"{label}: did not raise")

    def runner(name, status, *labels):
        return {"name": name, "status": status,
                "labels": [{"name": label} for label in ("self-hosted", *labels)]}

    fleet = [
        runner("imx8mpevk-04", "online", "Linux", "ARM64", "imx8mp", "imx8mp-evk"),
        runner("imx8mpevk-08", "offline", "Linux", "ARM64", "imx8mp", "imx8mp-evk",
               "camera"),
        runner("imx95-frdm", "online", "Linux", "ARM64", "imx95", "imx95-frdm"),
        runner("rpi5-hailo8l", "online", "Linux", "ARM64", "rpi5", "hailo8l"),
        runner("imx95-phytec", "offline", "Linux", "ARM64", "imx95", "imx95-phytec"),
        # GitHub reports labels in the casing they were first registered with.
        runner("mltrain-02", "online", "Linux", "X64", "CUDA"),
    ]

    def fake(org, token):
        check("fetch org", org, "EdgeFirstAI")
        check("fetch token", token, "t0ken")
        return fleet

    base = {"BOARDS": "imx8mp-evk", "TOKEN": "t0ken", "ORG": "EdgeFirstAI",
            "EVENT": "workflow_dispatch", "REPO": "EdgeFirstAI/hal"}

    r = resolve({**base, "BOARDS": "imx8mp-evk, rpi5, imx95-phytec, imx95-frdm+ara240"},
                fetch=fake)
    check("online entries kept", [e["runner"] for e in r["board_matrix"]],
          ["imx8mp-evk", "rpi5"])
    check("offline and unmatched reported", r["unavailable"], [
        {"runner": "imx95-phytec", "reason": "no online runner carries imx95-phytec"},
        {"runner": "imx95-frdm+ara240",
         "reason": "no online runner carries imx95-frdm, ara240"},
    ])
    check("online checked", r["online_checked"], True)

    # Every label must be on the same online runner: the only runner carrying
    # `camera` for this identity is offline.
    r = resolve({**base, "BOARDS": "imx8mp-evk+camera"}, fetch=fake)
    check("label set needs one runner with all labels", r["board_matrix"], [])

    check("case-insensitive match",
          resolve({**base, "BOARDS": "cuda"}, fetch=fake)["board_matrix"],
          [{"runner": "cuda", "labels": ["self-hosted", "cuda"]}])

    # Without a token nothing can be checked, so every entry is scheduled.
    def no_fetch(org, token):
        failures.append("fetched runners without a token")
        return []

    r = resolve({**base, "BOARDS": "imx95-phytec", "TOKEN": " "}, fetch=no_fetch)
    check("no token passes through", [e["runner"] for e in r["board_matrix"]],
          ["imx95-phytec"])
    check("no token not checked", r["online_checked"], False)

    # A fork never reaches the fleet, token or not.
    r = resolve({**base, "EVENT": "pull_request", "PR_HEAD_REPO": "someone/hal"},
                fetch=no_fetch)
    check("fork matrix empty", r["board_matrix"], [])
    check("fork reported", r["unavailable"],
          [{"runner": "imx8mp-evk", "reason": "untrusted trigger"}])

    check_raises("no boards", lambda: resolve({**base, "BOARDS": " "}, fetch=fake))

    def denied(org, token):
        raise LaneError("HTTP 403")

    check_raises("api failure is an error, not a pass-through",
                 lambda: resolve(base, fetch=denied))

    emitted = []

    class Sink:
        def write(self, text):
            emitted.append(text)

    _emit({"board_matrix": [], "unavailable": [], "online_checked": True}, Sink())
    check("empty matrix emits has_boards=false",
          "has_boards=false\n" in emitted, True)

    for f in failures:
        print(f"FAIL {f}", file=sys.stderr)
    print(f"resolve_boards self-test: {len(failures)} failure(s)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
