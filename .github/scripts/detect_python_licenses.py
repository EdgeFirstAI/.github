#!/usr/bin/env python3
"""Fill licence gaps in a Python dependency SBOM from the packages' own
licence files (Au-Zone SPS).

Some packages declare no licence the policy can classify: only an ambiguous
classifier ("License :: OSI Approved :: BSD License"), a bare word ("BSD"), or
nothing but a LICENSE file. For those components alone, the licence files the
installed distribution ships are scanned with scancode and the detected SPDX
expression is added to the component. The policy then decides on that licence
like any other; no package or version is named anywhere.

Without scancode the SBOM is left unchanged, so the gaps still fail the check.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Tuple

from check_license_policy import (
    RANK_UNKNOWN,
    evaluate_expression,
    licenses_from_component,
)


def normalize_name(name: str) -> str:
    """PEP 503 normalised distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def needs_detection(component: dict) -> bool:
    """True when no licence entry of the component classifies as a known
    licence, so the policy would reject it as unknown or missing."""
    licenses = licenses_from_component(component)
    return all(evaluate_expression(entry)[0] == RANK_UNKNOWN for entry in licenses)


_LICENSE_NAME = re.compile(r"^(licen[cs]e|copying|notice|copyright)", re.IGNORECASE)


def is_license_file(relative_path: str) -> bool:
    """A file a distribution installs that states its licence terms: one in
    its .dist-info directory's licenses/ (PEP 639), or a LICENSE, COPYING,
    NOTICE or COPYRIGHT file directly in .dist-info."""
    parts = relative_path.replace("\\", "/").split("/")
    if len(parts) < 2 or not parts[0].endswith(".dist-info"):
        return False
    if len(parts) > 2 and parts[1] == "licenses":
        return True
    return len(parts) == 2 and bool(_LICENSE_NAME.match(parts[1]))


def apply_detections(sbom: dict, detections: Dict[Tuple[str, str], str]) -> List[str]:
    """Add each detected expression to the matching gap component; return
    `name@version: expression` lines for the ones changed."""
    changed: List[str] = []
    for component in sbom.get("components") or []:
        name = component.get("name") or ""
        version = component.get("version") or ""
        expression = detections.get((normalize_name(name), version))
        if not expression or not needs_detection(component):
            continue
        component["licenses"] = list(component.get("licenses") or []) + [
            {"expression": expression}
        ]
        changed.append(f"{name}@{version}: {expression}")
    return changed


# Run with the dependency environment's own interpreter: every installed
# distribution with the files of its .dist-info directory.
_INVENTORY = """
import importlib.metadata as md, json, sys
out = []
for dist in md.distributions():
    files = []
    for f in dist.files or []:
        rel = str(f)
        if rel.split("/")[0].endswith(".dist-info"):
            files.append([rel, str(dist.locate_file(f))])
    out.append({"name": dist.metadata["Name"], "version": dist.version, "files": files})
json.dump(out, sys.stdout)
"""


def combine(expressions: List[str]) -> str:
    """Every licence file of a package applies, so their terms are ANDed."""
    unique = list(dict.fromkeys(expressions))
    if len(unique) == 1:
        return unique[0]
    return " AND ".join(f"({e})" if " " in e else e for e in unique)


def detect(python: str, scancode: str, gaps: Dict[Tuple[str, str], str]) -> Dict[Tuple[str, str], str]:
    """Scan the licence files of the gap distributions installed in the
    environment of `python`; return (normalised name, version) -> SPDX."""
    inventory = json.loads(
        subprocess.run([python, "-c", _INVENTORY], check=True, capture_output=True, text=True).stdout
    )
    stage = tempfile.mkdtemp(prefix="python-licenses-")
    try:
        staged = 0
        for dist in inventory:
            key = (normalize_name(dist["name"] or ""), dist["version"])
            if key not in gaps:
                continue
            for rel, path in dist["files"]:
                if is_license_file(rel) and os.path.isfile(path):
                    target = os.path.join(stage, f"{key[0]}@{key[1]}", rel)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copyfile(path, target)
                    staged += 1
        if not staged:
            return {}
        scan = os.path.join(stage, "scan.json")
        subprocess.run(
            [scancode, "--quiet", "--license", "-n", "2", "--json", scan,
             os.path.join(stage, ".")],
            check=True,
        )
        with open(scan, encoding="utf-8") as handle:
            results = json.load(handle)
        found: Dict[Tuple[str, str], List[str]] = {}
        for entry in results.get("files") or []:
            expression = entry.get("detected_license_expression_spdx")
            if entry.get("type") != "file" or not expression:
                continue
            for part in entry["path"].split("/"):
                name, sep, version = part.partition("@")
                if sep and (name, version) in gaps:
                    found.setdefault((name, version), []).append(expression)
                    break
        return {key: combine(values) for key, values in found.items()}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def run_self_test() -> int:
    failures: List[str] = []
    classifier = {"license": {"name": "License :: OSI Approved :: BSD License"}}
    declared_bsd = {"license": {"name": "declared license of 'x'", "text": {"content": "BSD"}}}
    cases = [
        ({"licenses": []}, True),
        ({}, True),
        ({"licenses": [classifier]}, True),
        ({"licenses": [classifier, declared_bsd]}, True),
        ({"licenses": [{"license": {"id": "MIT"}}]}, False),
        ({"licenses": [classifier, {"license": {"id": "Apache-2.0"}}]}, False),
        # A known but rejected licence is a decision, not a gap to fill.
        ({"licenses": [{"license": {"id": "GPL-3.0"}}]}, False),
        ({"licenses": [{"license": {"name": "NXP Proprietary"}}]}, False),
    ]
    for component, expected in cases:
        got = needs_detection(component)
        if got != expected:
            failures.append(f"  needs_detection({component!r}): expected {expected}, got {got}")

    files = [
        ("namex-0.1.0.dist-info/licenses/LICENSE", True),
        ("astunparse-1.6.3.dist-info/LICENSE", True),
        ("foo-1.0.dist-info/LICENSE.txt", True),
        ("foo-1.0.dist-info/COPYING", True),
        ("foo-1.0.dist-info/licenses/NOTICE", True),
        ("foo-1.0.dist-info/METADATA", False),
        ("foo-1.0.dist-info/RECORD", False),
        ("foo/license_check.py", False),
        ("foo/__init__.py", False),
    ]
    for path, expected in files:
        if is_license_file(path) != expected:
            failures.append(f"  is_license_file({path!r}): expected {expected}")

    sbom = {
        "components": [
            {"name": "namex", "version": "0.1.0"},
            {"name": "Safe_Tensors", "version": "0.8.0", "licenses": [classifier]},
            {"name": "keras", "version": "3.15.1", "licenses": [{"license": {"id": "Apache-2.0"}}]},
            {"name": "orphan", "version": "1.0"},
        ]
    }
    changed = apply_detections(
        sbom,
        {
            ("namex", "0.1.0"): "Apache-2.0",
            ("safe-tensors", "0.8.0"): "Apache-2.0",
            ("keras", "3.15.1"): "GPL-3.0",
        },
    )
    by_name = {c["name"]: c for c in sbom["components"]}
    if {"expression": "Apache-2.0"} not in (by_name["namex"].get("licenses") or []):
        failures.append("  namex: detected expression not added")
    if {"expression": "Apache-2.0"} not in by_name["Safe_Tensors"]["licenses"]:
        failures.append("  Safe_Tensors: name normalisation did not match")
    if len(by_name["keras"]["licenses"]) != 1:
        failures.append("  keras: a component with a known licence was changed")
    if by_name["orphan"].get("licenses"):
        failures.append("  orphan: changed without a detection")
    if sorted(changed) != ["Safe_Tensors@0.8.0: Apache-2.0", "namex@0.1.0: Apache-2.0"]:
        failures.append(f"  changed lines: {changed}")

    if failures:
        print("detect_python_licenses self-test FAILED:")
        print("\n".join(failures))
        return 1
    print(f"detect_python_licenses self-test passed ({len(cases) + len(files) + 5} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run the self-test and exit")
    parser.add_argument("sbom", nargs="?", help="CycloneDX JSON SBOM of the environment, updated in place")
    parser.add_argument("--python", help="Interpreter of the environment the SBOM describes")
    parser.add_argument("--scancode", help="scancode executable; without it the SBOM is unchanged")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    if not args.sbom or not args.python:
        parser.error("sbom and --python are required unless --self-test is given")

    with open(args.sbom, encoding="utf-8") as handle:
        sbom = json.load(handle)
    gaps = {
        (normalize_name(c.get("name") or ""), c.get("version") or ""): c.get("name") or ""
        for c in sbom.get("components") or []
        if needs_detection(c)
    }
    if not gaps:
        return 0
    if not args.scancode:
        print(f"licence files not scanned (no scancode): {len(gaps)} component(s) without a readable licence")
        return 0
    changed = apply_detections(sbom, detect(args.python, args.scancode, gaps))
    with open(args.sbom, "w", encoding="utf-8") as handle:
        json.dump(sbom, handle, indent=2)
        handle.write("\n")
    for line in changed:
        print(f"licence detected from its licence files: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
