#!/usr/bin/env python3
"""Resolve rust-full.yml lane selection and runner classes.

Configuration arrives as environment variables and results are appended to
$GITHUB_OUTPUT. Run with --self-test to execute the unit tests; ci.yml does.
"""

import json
import os
import sys


HOSTED = {
    "linux": "ubuntu-24.04",
    "linux-arm": "ubuntu-24.04-arm",
    "macos": "macos-latest",
    "windows": "windows-latest",
}

# The fourth label is a capability claim. A build box is labelled `build`;
# `d3d11` and `metal` are reserved for machines that genuinely have them, so
# that a mislabelled lane queues rather than failing at runtime.
FLEET = {
    "linux": ["self-hosted", "linux", "x64", "build"],
    "linux-arm": ["self-hosted", "linux", "arm64", "build"],
    "macos": ["self-hosted", "macos", "arm64", "build"],
    "windows": ["self-hosted", "windows", "x64", "build"],
}

LARGER = {
    "linux": "ubuntu-24.04-xlarge",
    "linux-arm": "ubuntu-24.04-arm-xlarge",
    "macos": "macos-latest-xlarge",
    # Requires an org-provisioned Windows larger runner; without one this
    # label queues until the job times out.
    "windows": "windows-latest-8-cores",
}

# The GPU lane is self-hosted by definition: there is no hosted or billed
# CUDA equivalent to choose between, so no runner-class input governs it.
GPU_RUNNER = ["self-hosted", "linux", "x64", "CUDA"]

# Events that cannot carry a fork's code. Anything not named here is
# untrusted: an allowlist of events under which to *check* reopens on
# every new event type, and workflow_run and pull_request_target both
# run a fork's head. Unlike yocto-build, an untrusted event here
# degrades to hosted runners rather than failing -- there is a hosted
# fallback, so refusing outright would be gratuitous.
TRUSTED_EVENTS = frozenset({"push", "workflow_dispatch", "schedule", "merge_group"})

CLASSES = {"hosted": HOSTED, "fleet": FLEET, "larger": LARGER}
LANE_NAMES = {"host", "hardware", "gpu"}


class LaneError(ValueError):
    pass


def map_class(cls, kind):
    if cls not in CLASSES:
        raise LaneError(f"unknown runner-class '{cls}' (use hosted|fleet|larger)")
    return CLASSES[cls][kind]


def parse_lanes(raw):
    """Parse the comma-separated lane set.

    `all` expands to host+hardware, preserving its prior meaning exactly.
    `gpu` is never implied by `all`: every migrated repository passes `all`,
    and two CUDA machines cannot absorb the whole fleet's Full tier.
    """
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    if not tokens:
        raise LaneError("lanes must not be empty (use all|host|hardware|gpu)")
    lanes = set()
    for token in tokens:
        if token == "all":
            lanes |= {"host", "hardware"}
        elif token in LANE_NAMES:
            lanes.add(token)
        else:
            raise LaneError(f"unknown lane '{token}' (use all|host|hardware|gpu)")
    return lanes


def resolve(env):
    lanes = parse_lanes(env.get("LANES", "all"))
    classes = {
        "linux": env.get("CLASS_LINUX") or "hosted",
        "linux-arm": env.get("CLASS_ARM") or "hosted",
        "macos": env.get("CLASS_MAC") or "hosted",
        "windows": env.get("CLASS_WIN") or "hosted",
    }

    event = env.get("EVENT") or ""
    if event in TRUSTED_EVENTS:
        same_repo = True
    elif event == "pull_request":
        same_repo = env.get("PR_HEAD_REPO") == env.get("REPO")
    else:
        same_repo = False

    do_host = "host" in lanes
    do_hardware = "hardware" in lanes
    do_gpu = "gpu" in lanes and bool((env.get("GPU_ARGS") or "").strip())

    if not same_repo:
        # A fork PR's pre-command and build scripts are attacker-controlled.
        # Self-hosted capacity must be unreachable from one.
        classes = {kind: "hosted" for kind in classes}
        do_hardware = False
        do_gpu = False

    boards = [b.strip() for b in (env.get("BOARDS") or "").split(",") if b.strip()]
    if not boards:
        do_hardware = False
    board_matrix = [{"runner": b} for b in boards] if do_hardware else []

    return {
        "linux": map_class(classes["linux"], "linux"),
        "linux_arm": map_class(classes["linux-arm"], "linux-arm"),
        "macos": map_class(classes["macos"], "macos"),
        "windows": map_class(classes["windows"], "windows"),
        "gpu": GPU_RUNNER,
        "do_host": do_host,
        "do_arm": do_host or do_hardware,
        "do_macos": do_host and (env.get("SKIP_MAC") or "") != "true",
        "do_windows": do_host and (env.get("SKIP_WIN") or "") != "true",
        "do_hardware": do_hardware,
        "do_gpu": do_gpu,
        "do_nightly": (env.get("NIGHTLY") or "false"),
        "same_repo": same_repo,
        "board_matrix": board_matrix,
    }


def _emit(result, stream):
    for key, value in result.items():
        if key in ("linux", "linux_arm", "macos", "windows", "gpu"):
            stream.write(f"{key}={json.dumps(value)}\n")
        elif key == "board_matrix":
            stream.write(f"board_matrix<<EOF\n{json.dumps(value)}\nEOF\n")
        elif isinstance(value, bool):
            stream.write(f"{key}={'true' if value else 'false'}\n")
        else:
            stream.write(f"{key}={value}\n")


def main():
    try:
        result = resolve(os.environ)
    except LaneError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
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

    # `all` keeps its exact prior meaning and never implies gpu.
    check("all", parse_lanes("all"), {"host", "hardware"})
    check("host", parse_lanes("host"), {"host"})
    check("hardware", parse_lanes("hardware"), {"hardware"})
    check("gpu alone", parse_lanes("gpu"), {"gpu"})
    check("host,gpu", parse_lanes("host,gpu"), {"host", "gpu"})
    check("all,gpu", parse_lanes("all,gpu"), {"host", "hardware", "gpu"})
    check("whitespace", parse_lanes(" host , gpu "), {"host", "gpu"})
    check_raises("unknown lane", lambda: parse_lanes("bogus"))
    check_raises("empty lanes", lambda: parse_lanes("   "))

    # The windows and macos fleet tuples claim build capability, not graphics.
    check("fleet windows", map_class("fleet", "windows"),
          ["self-hosted", "windows", "x64", "build"])
    check("fleet macos", map_class("fleet", "macos"),
          ["self-hosted", "macos", "arm64", "build"])
    check("hosted linux", map_class("hosted", "linux"), "ubuntu-24.04")
    check("larger linux", map_class("larger", "linux"), "ubuntu-24.04-xlarge")
    check_raises("unknown class", lambda: map_class("bogus", "linux"))

    base = {
        "LANES": "all", "BOARDS": "imx8mp-evk", "CLASS_LINUX": "fleet",
        "CLASS_ARM": "fleet", "CLASS_MAC": "hosted", "CLASS_WIN": "hosted",
        "EVENT": "push", "REPO": "EdgeFirstAI/hal", "GPU_ARGS": "",
    }

    r = resolve(base)
    check("same-repo hardware", r["do_hardware"], True)
    check("board matrix", r["board_matrix"], [{"runner": "imx8mp-evk"}])
    check("all never implies gpu", r["do_gpu"], False)

    # Requested but unconfigured: exercises the gpu-args guard itself rather
    # than passing because `all` happens not to contain gpu.
    check("gpu requested without gpu-args",
          resolve({**base, "LANES": "all,gpu"})["do_gpu"], False)
    check("gpu requested with blank gpu-args",
          resolve({**base, "LANES": "gpu", "GPU_ARGS": "   "})["do_gpu"], False)

    r = resolve({**base, "LANES": "all,gpu", "GPU_ARGS": "--features cuda"})
    check("gpu enabled", r["do_gpu"], True)
    check("gpu runner", r["gpu"], ["self-hosted", "linux", "x64", "CUDA"])

    # A fork PR loses every self-hosted lane and every non-hosted class.
    fork = {**base, "LANES": "all,gpu", "GPU_ARGS": "--features cuda",
            "EVENT": "pull_request", "PR_HEAD_REPO": "someone/hal"}
    r = resolve(fork)
    check("fork hardware off", r["do_hardware"], False)
    check("fork gpu off", r["do_gpu"], False)
    check("fork class downgraded", r["linux"], "ubuntu-24.04")
    check("fork board matrix empty", r["board_matrix"], [])

    # No boards named means no hardware lane even when requested.
    r = resolve({**base, "BOARDS": ""})
    check("no boards", r["do_hardware"], False)

    # do_arm follows host or hardware, as before.
    check("arm follows host", resolve({**base, "LANES": "host"})["do_arm"], True)
    check("arm off for gpu only",
          resolve({**base, "LANES": "gpu", "GPU_ARGS": "-x"})["do_arm"], False)

    # do_macos and do_windows are gated by host lane and skip flags.
    r = resolve({**base, "LANES": "host"})
    check("do_macos enabled", r["do_macos"], True)
    check("do_windows enabled", r["do_windows"], True)
    check("do_macos skipped", resolve({**base, "LANES": "host", "SKIP_MAC": "true"})["do_macos"], False)
    check("do_windows skipped", resolve({**base, "LANES": "host", "SKIP_WIN": "true"})["do_windows"], False)
    check("do_macos off when no host", resolve({**base, "LANES": "hardware"})["do_macos"], False)
    check("do_windows off when no host", resolve({**base, "LANES": "hardware"})["do_windows"], False)

    # Fork PR downgrade applies to all four runner classes, not just linux.
    fork = {**base, "LANES": "all,gpu", "GPU_ARGS": "--features cuda",
            "EVENT": "pull_request", "PR_HEAD_REPO": "someone/hal"}
    r = resolve(fork)
    check("fork linux downgraded", r["linux"], "ubuntu-24.04")
    check("fork linux_arm downgraded", r["linux_arm"], "ubuntu-24.04-arm")
    check("fork macos downgraded", r["macos"], "macos-latest")
    check("fork windows downgraded", r["windows"], "windows-latest")

    # pull_request_target from a fork repo is treated same as fork pull_request.
    fork_target = {**base, "LANES": "all,gpu", "GPU_ARGS": "--features cuda",
                   "EVENT": "pull_request_target", "PR_HEAD_REPO": "someone/hal"}
    r = resolve(fork_target)
    check("pull_request_target fork hardware off", r["do_hardware"], False)
    check("pull_request_target fork gpu off", r["do_gpu"], False)
    check("pull_request_target fork linux downgraded", r["linux"], "ubuntu-24.04")

    # workflow_run runs a fork's head under the base repo's trust. Untrusted
    # like any unnamed event: hardware and gpu off, every class hosted.
    workflow_run = {**base, "LANES": "all,gpu", "GPU_ARGS": "--features cuda",
                     "EVENT": "workflow_run"}
    r = resolve(workflow_run)
    check("workflow_run same_repo", r["same_repo"], False)
    check("workflow_run hardware off", r["do_hardware"], False)
    check("workflow_run gpu off", r["do_gpu"], False)
    check("workflow_run linux hosted", r["linux"], "ubuntu-24.04")
    check("workflow_run linux_arm hosted", r["linux_arm"], "ubuntu-24.04-arm")
    check("workflow_run macos hosted", r["macos"], "macos-latest")
    check("workflow_run windows hosted", r["windows"], "windows-latest")

    # Trusted events never carry a fork's code and are always same-repo.
    for trusted_event in ("merge_group", "push", "schedule", "workflow_dispatch"):
        check(f"{trusted_event} same_repo",
              resolve({**base, "EVENT": trusted_event})["same_repo"], True)

    # A same-repo pull_request is trusted; a fork pull_request is not.
    check("same-repo pull_request same_repo",
          resolve({**base, "EVENT": "pull_request",
                   "PR_HEAD_REPO": base["REPO"]})["same_repo"], True)
    check("fork pull_request same_repo",
          resolve({**base, "EVENT": "pull_request",
                   "PR_HEAD_REPO": "someone/hal"})["same_repo"], False)

    for f in failures:
        print(f"FAIL {f}", file=sys.stderr)
    print(f"resolve_lanes self-test: {len(failures)} failure(s)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
