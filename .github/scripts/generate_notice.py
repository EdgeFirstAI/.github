#!/usr/bin/env python3
"""Generate NOTICE from a CycloneDX SBOM (Au-Zone SPS).

NOTICE names every component the SBOM lists (validate_notice.py enforces it).
This writes that list: the repository's own text above the
"Third-Party Components" heading is kept as written, and everything from that
heading down is generated from the SBOM, one line per component with the
licence the licence check applies to it, bundled libraries under their
package. A NOTICE without the heading keeps all of its text as the header; a
repository without NOTICE gets a header naming the project and its copyright.

    generate_notice.py sbom/sbom.json                 # rewrite ./NOTICE
    generate_notice.py sbom.json --output NOTICE.new  # leave NOTICE as is
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import List, Optional, Tuple

from check_license_policy import (
    FIRST_PARTY_PROPERTY,
    LINKAGE_PROPERTY,
    is_first_party,
    RANK_PROPRIETARY,
    evaluate_expression,
    licenses_from_component,
)

HEADING = "Third-Party Components"

INTRO = (
    "These components are installed with this software, transitive dependencies\n"
    "and the libraries a package bundles included. Each is listed with the\n"
    "license the release license check applies to it:"
)
CLOSING = (
    "The release SBOM (sbom.json) built for each release records each component's\n"
    "version and the evidence for its license."
)
NAME_COLUMN = 40
BUNDLED = "  bundles "


def judged_licence(component: dict) -> Tuple[str, Optional[int]]:
    """The licence entry the check decides on, the best-ranked of the
    component's alternatives, and its rank."""
    entries = licenses_from_component(component)
    if not entries:
        return "UNKNOWN", None
    best = min(entries, key=lambda entry: evaluate_expression(entry)[0])
    return best, evaluate_expression(best)[0]


def notice_header(existing: Optional[str], project: str, year: int) -> str:
    """The repository's own text: everything above the third-party heading,
    or the whole NOTICE when it has none; for no NOTICE, the project and its
    copyright."""
    if existing is None or not existing.strip():
        return f"{project}\nCopyright (c) {year} Au-Zone Technologies Inc.\n"
    kept: List[str] = []
    for line in existing.splitlines():
        if line.strip() == HEADING:
            break
        kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def _component_lines(components: List[dict], indent: str) -> List[str]:
    lines: List[str] = []
    for component in sorted(components, key=lambda c: (c.get("name") or "").lower()):
        name = component.get("name") or ""
        if is_first_party(component):
            # The repository's own package is not a third-party component; the
            # libraries it bundles are, listed where it would have been.
            lines.extend(_component_lines(component.get("components") or [], indent))
            continue
        if not name:
            continue
        licence, rank = judged_licence(component)
        linkage = {p.get("value") for p in component.get("properties") or []
                   if p.get("name") == LINKAGE_PROPERTY}
        note = ""
        if linkage == {"dynamic"}:
            note = "  (bundled shared library, loaded dynamically)"
        elif rank == RANK_PROPRIETARY:
            note = "  (proprietary; approved in .github/license-approvals.json)"
        lines.append(f"{(indent + name).ljust(NAME_COLUMN)}  {licence}{note}")
        lines.extend(_component_lines(component.get("components") or [], indent + BUNDLED))
    return lines


def render_notice(sbom: dict, existing: Optional[str], year: int) -> str:
    """NOTICE text: the repository's header, then every SBOM component."""
    project = ((sbom.get("metadata") or {}).get("component") or {}).get("name") or "This project"
    section = "\n".join([
        HEADING,
        "=" * len(HEADING),
        "",
        INTRO,
        "",
        *_component_lines(sbom.get("components") or [], "    "),
        "",
        CLOSING,
    ])
    return notice_header(existing, project, year) + "\n" + section + "\n"


def run_self_test() -> int:
    from validate_notice import notice_gaps

    failures: List[str] = []
    sbom = {
        "metadata": {"component": {"name": "probe-app"}},
        "components": [
            {"name": "zlib-py", "licenses": [{"expression": "Zlib"}]},
            {"name": "numpy", "licenses": [{"license": {"name": "License :: OSI Approved :: BSD License"}},
                                           {"expression": "BSD-3-Clause"}],
             "components": [{"name": "libquadmath", "licenses": [{"license": {"name": "LGPL-2.1-or-later"}}],
                             "properties": [{"name": LINKAGE_PROPERTY, "value": "dynamic"}]}]},
            {"name": "Vendor-SDK", "licenses": [{"license": {"name": "Vendor Proprietary EULA"}}]},
            {"name": "probe-app-core", "licenses": [{"expression": "LicenseRef-EdgeFirst-Proprietary"}],
             "properties": [{"name": FIRST_PARTY_PROPERTY, "value": "true"}],
             "components": [{"name": "libvendored", "licenses": [{"expression": "MIT"}]}]},
        ],
    }
    existing = (
        "Probe App\nCopyright (c) 2026 Au-Zone Technologies Inc.\n\n"
        "First-Party Components\n======================\n\n    probe-app\n\n"
        "Third-Party Components\n======================\n\n    stale-package  MIT\n"
    )
    notice = render_notice(sbom, existing, 2026)

    checks = [
        ("keeps the repository's header", notice.startswith(existing.split(HEADING)[0])),
        ("drops the previous list", "stale-package" not in notice),
        ("names the heading once", notice.count(HEADING) == 1),
        ("names every component", notice_gaps(sbom, notice) == []),
        ("lists the licence the check applies", "numpy" in notice and "BSD-3-Clause" in notice),
        ("lists a bundled library under its package",
         notice.index("numpy") < notice.index("bundles libquadmath") < notice.index("Vendor-SDK")),
        ("marks a dynamically loaded library", "loaded dynamically" in notice.split("libquadmath")[1].splitlines()[0]),
        ("marks a proprietary component", "proprietary" in notice.split("Vendor-SDK")[1].splitlines()[0]),
        ("sorts by name, ignoring case", notice.index("numpy") < notice.index("Vendor-SDK") < notice.index("zlib-py")),
        ("is stable when run again", render_notice(sbom, notice, 2026) == notice),
        ("leaves the repository's own package out", "probe-app-core" not in notice),
        ("lists what the repository's own package bundles",
         "\n    libvendored" in notice and "bundles libvendored" not in notice),
        ("keeps a NOTICE without the heading whole",
         render_notice(sbom, "Probe App\nCopyright (c) 2026 Au-Zone\n", 2026).startswith("Probe App\nCopyright (c) 2026 Au-Zone\n\n" + HEADING)),
    ]
    fresh = render_notice(sbom, None, 2031)
    checks += [
        ("names the project without a NOTICE", fresh.startswith("probe-app\nCopyright (c) 2031 Au-Zone Technologies Inc.\n")),
        ("names every component without a NOTICE", notice_gaps(sbom, fresh) == []),
    ]
    for label, ok in checks:
        if not ok:
            failures.append(f"  {label}")
    if failures:
        print("generate_notice self-test FAILED:")
        print("\n".join(failures))
        print(notice)
        return 1
    print(f"generate_notice self-test passed ({len(checks)} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="Run the self-test and exit")
    parser.add_argument("sbom", nargs="?", help="CycloneDX JSON SBOM")
    parser.add_argument("--notice", default=os.environ.get("NOTICE_FILE", "NOTICE"),
                        help="NOTICE whose header is kept (default: NOTICE)")
    parser.add_argument("--output", help="Where to write; default: rewrite --notice")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    if not args.sbom:
        parser.error("sbom is required unless --self-test is given")
    with open(args.sbom, encoding="utf-8") as handle:
        sbom = json.load(handle)
    existing = None
    if os.path.isfile(args.notice):
        with open(args.notice, encoding="utf-8") as handle:
            existing = handle.read()
    notice = render_notice(sbom, existing, datetime.date.today().year)
    output = args.output or args.notice
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(notice)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
