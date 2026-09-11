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
from typing import Iterable, List, Set

PROPRIETARY_MARKERS = (
    "proprietary",
    "LA_OPT_NXP",
    "NXP Proprietary",
    "NXP-Proprietary",
)


def licenses_of(component: dict) -> List[str]:
    found: List[str] = []
    for entry in component.get("licenses") or []:
        license_obj = entry.get("license") or {}
        if "id" in license_obj:
            found.append(license_obj["id"])
        elif "name" in license_obj:
            found.append(license_obj["name"])
        elif "expression" in entry:
            found.append(entry["expression"])
    return found


def iter_components(sbom: dict) -> Iterable[dict]:
    for component in sbom.get("components") or []:
        yield component


def is_proprietary(component: dict) -> bool:
    blob = " ".join(licenses_of(component)).lower()
    return any(marker.lower() in blob for marker in PROPRIETARY_MARKERS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbom", nargs="?", help="CycloneDX JSON path")
    parser.add_argument(
        "--notice",
        default=os.environ.get("NOTICE_FILE", "NOTICE"),
        help="NOTICE file path",
    )
    args = parser.parse_args()

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
