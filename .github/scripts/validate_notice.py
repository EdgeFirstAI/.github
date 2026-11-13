#!/usr/bin/env python3
"""Validate NOTICE against a CycloneDX SBOM.

NOTICE must exist, carry a copyright line, and name every component the SBOM
lists, transitive dependencies and the libraries a package bundles included,
whatever their licence: what ships is attributed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List

# Components are walked as the licence check walks them, nested ones (the
# libraries a package bundles) included.
from check_license_policy import FIRST_PARTY_PROPERTY, third_party_components


def notice_gaps(sbom: dict, text: str) -> List[str]:
    """Third-party components NOTICE does not name, each once, in SBOM order.
    The repository's own packages are not third-party and need no entry."""
    notice_lower = text.lower()
    missing: List[str] = []
    for component in third_party_components(sbom):
        name = component.get("name") or ""
        if name and name.lower() not in notice_lower and name not in missing:
            missing.append(name)
    return missing


def _declared(text: str) -> dict:
    return {"license": {"name": "declared license of 'vendor-sdk'", "text": {"content": text}}}


# (licenses of one component named vendor-sdk, NOTICE text, required gap?)
SELF_TEST_CASES = [
    ([_declared("NXP Proprietary")], "Copyright 2026 Au-Zone", True),
    ([_declared("NXP Proprietary")], "Copyright 2026 Au-Zone\nvendor-sdk: NXP", False),
    ([{"license": {"id": "LA_OPT_NXP_SW"}}], "Copyright 2026 Au-Zone", True),
    ([{"license": {"name": "Vendor Proprietary EULA"}}], "Copyright", True),
    # Every component is named, whatever its licence.
    ([_declared("Apache License 2.0")], "Copyright 2026 Au-Zone", True),
    ([_declared("Apache License 2.0")], "Copyright 2026 Au-Zone\nvendor-sdk: Apache-2.0", False),
    ([{"expression": "LGPL-2.1-or-later"}], "Copyright 2026 Au-Zone", True),
]


def run_self_test() -> int:
    failures = []
    for licenses, text, expected in SELF_TEST_CASES:
        sbom = {"components": [{"name": "vendor-sdk", "version": "1.0.0", "licenses": licenses}]}
        required = notice_gaps(sbom, text)
        if bool(required) != expected:
            failures.append(f"  {licenses!r} / {text!r}: required gap expected {expected}, got {required}")
    # The libraries a package bundles, as detect_licenses.py nests them, are
    # named too: a proprietary one and a dynamically loaded LGPL one alike.
    nested = {"components": [{
        "name": "host-package", "version": "1.0.0", "licenses": [_declared("Apache License 2.0")],
        "components": [
            {"name": "vendor-blob", "licenses": [{"license": {"name": "Vendor Proprietary EULA"}}]},
            {"name": "libquadmath", "licenses": [{"license": {"name": "LGPL-2.1-or-later"}}]},
        ],
    }]}
    required = notice_gaps(nested, "Copyright 2026 Au-Zone\nhost-package")
    if required != ["vendor-blob", "libquadmath"]:
        failures.append(f"  nested libraries: required gaps expected ['vendor-blob', 'libquadmath'], got {required}")
    # The repository's own package needs no entry; what it bundles still does.
    own = {"components": [{
        "name": "edgefirst-app", "version": "1.0.0",
        "licenses": [{"expression": "LicenseRef-EdgeFirst-Proprietary"}],
        "properties": [{"name": FIRST_PARTY_PROPERTY, "value": "true"}],
        "components": [{"name": "libbundled", "licenses": [{"expression": "MIT"}]}],
    }]}
    required = notice_gaps(own, "Copyright 2026 Au-Zone")
    if required != ["libbundled"]:
        failures.append(f"  first-party package: required gaps expected ['libbundled'], got {required}")
    if failures:
        print("validate_notice self-test FAILED:")
        print("\n".join(failures))
        return 1
    print(f"validate_notice self-test passed ({len(SELF_TEST_CASES) + 2} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Check NOTICE gap detection against known cases and exit",
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

    missing = notice_gaps(sbom, text)
    if missing:
        print(f"ERROR: {len(missing)} SBOM components missing from {args.notice}:")
        for name in missing:
            print(f"  - {name}")
        return 1
    print(f"{args.notice}: valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
