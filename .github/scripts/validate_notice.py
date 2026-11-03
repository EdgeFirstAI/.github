#!/usr/bin/env python3
"""Validate NOTICE against a CycloneDX SBOM.

NOTICE must exist, carry a copyright line, and name every proprietary or
review-required component. First-level attribution of remaining components
is warned, not failed, so NOTICE stays a human document rather than a dump
of the full transitive graph.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Iterable, List, Set, Tuple

# The licence check's reading of a component's licences, declared licence text
# included, so a proprietary declaration is seen by both checks.
from check_license_policy import licenses_from_component

PROPRIETARY_MARKERS = (
    "proprietary",
    "LA_OPT_NXP",
    "NXP Proprietary",
    "NXP-Proprietary",
)


def iter_components(sbom: dict) -> Iterable[dict]:
    for component in sbom.get("components") or []:
        yield component


def is_proprietary(component: dict) -> bool:
    blob = " ".join(licenses_from_component(component)).lower()
    return any(marker.lower() in blob for marker in PROPRIETARY_MARKERS)


def notice_gaps(sbom: dict, text: str) -> Tuple[List[str], Set[str]]:
    """Components NOTICE must name but does not (proprietary), and the other
    components it does not name."""
    notice_lower = text.lower()
    missing_required: List[str] = []
    missing_optional: Set[str] = set()
    for component in iter_components(sbom):
        name = component.get("name") or ""
        if not name:
            continue
        if is_proprietary(component) and name.lower() not in notice_lower:
            missing_required.append(name)
        elif name.lower() not in notice_lower:
            missing_optional.add(name)
    return missing_required, missing_optional


def _declared(text: str) -> dict:
    return {"license": {"name": "declared license of 'vendor-sdk'", "text": {"content": text}}}


# (licenses of one component named vendor-sdk, NOTICE text, required gap?)
SELF_TEST_CASES = [
    ([_declared("NXP Proprietary")], "Copyright 2026 Au-Zone", True),
    ([_declared("NXP Proprietary")], "Copyright 2026 Au-Zone\nvendor-sdk: NXP", False),
    ([{"license": {"id": "LA_OPT_NXP_SW"}}], "Copyright 2026 Au-Zone", True),
    ([{"license": {"name": "Vendor Proprietary EULA"}}], "Copyright", True),
    ([_declared("Apache License 2.0")], "Copyright 2026 Au-Zone", False),
]


def run_self_test() -> int:
    failures = []
    for licenses, text, expected in SELF_TEST_CASES:
        sbom = {"components": [{"name": "vendor-sdk", "version": "1.0.0", "licenses": licenses}]}
        required, _optional = notice_gaps(sbom, text)
        if bool(required) != expected:
            failures.append(f"  {licenses!r} / {text!r}: required gap expected {expected}, got {required}")
    if failures:
        print("validate_notice self-test FAILED:")
        print("\n".join(failures))
        return 1
    print(f"validate_notice self-test passed ({len(SELF_TEST_CASES)} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Check proprietary detection against known cases and exit",
    )
    parser.add_argument("sbom", nargs="?", help="CycloneDX JSON path")
    parser.add_argument(
        "--notice",
        default=os.environ.get("NOTICE_FILE", "NOTICE"),
        help="NOTICE file path",
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if not os.path.isfile(args.notice):
        print(f"ERROR: {args.notice} is missing")
        return 1

    text = open(args.notice, encoding="utf-8").read()
    if not text.strip():
        print(f"ERROR: {args.notice} is empty")
        return 1
    if not re.search(r"copyright", text, re.IGNORECASE):
        print(f"ERROR: {args.notice} has no Copyright line")
        return 1

    if not args.sbom:
        print(f"{args.notice}: copyright present")
        return 0

    with open(args.sbom, encoding="utf-8") as handle:
        sbom = json.load(handle)

    missing_required, missing_optional = notice_gaps(sbom, text)

    if missing_required:
        print("ERROR: proprietary/review components missing from NOTICE:")
        for name in missing_required:
            print(f"  - {name}")
        return 1

    if missing_optional:
        preview = sorted(missing_optional)[:20]
        print(
            f"WARNING: {len(missing_optional)} SBOM components not named in "
            f"NOTICE (showing up to 20): {', '.join(preview)}"
        )
    print(f"{args.notice}: valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
