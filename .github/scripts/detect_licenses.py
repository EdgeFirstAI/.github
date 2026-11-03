#!/usr/bin/env python3
"""Fill licence gaps in a dependency SBOM from the components' own licence
texts (Au-Zone SPS).

Some packages declare no licence the policy can classify: a Python package
with only an ambiguous classifier ("License :: OSI Approved :: BSD License"),
a bare word ("BSD") or nothing but a LICENSE file; a crate with a
`license-file` instead of an SPDX `license`. For those components alone, their
licence texts are scanned with scancode and the detected SPDX expression is
added to the component: the texts the SBOM already carries (cargo-cyclonedx
embeds a crate's license-file) and, for a Python environment, the licence
files each installed distribution ships. The policy then decides on that
licence like any other; no package or version is named anywhere.

Without scancode the SBOM is left unchanged, so the gaps still fail the check.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

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


def embedded_texts(component: dict) -> List[str]:
    """Whole licence texts the SBOM carries for the component, such as the
    license-file cargo-cyclonedx embeds for a crate without an SPDX licence.
    A short declared identifier ("BSD") is not a licence text."""
    texts: List[str] = []
    for entry in component.get("licenses") or []:
        attached = (entry.get("license") or {}).get("text") or {}
        content = attached.get("content") or ""
        if attached.get("encoding") == "base64":
            try:
                content = base64.b64decode(content).decode("utf-8", errors="replace")
            except (ValueError, TypeError):
                continue
        if "\n" in content.strip() or len(content.strip()) > 64:
            texts.append(content)
    return texts


def combine(expressions: List[str]) -> str:
    """Every licence file of a package applies, so their terms are ANDed."""
    unique = list(dict.fromkeys(expressions))
    if len(unique) == 1:
        return unique[0]
    return " AND ".join(f"({e})" if " " in e else e for e in unique)


def _stage(stage: str, key: Tuple[str, str], relative: str) -> str:
    target = os.path.join(stage, f"{key[0]}@{key[1]}", relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


def detect(
    sbom: dict,
    scancode: str,
    python: Optional[str] = None,
) -> Dict[Tuple[str, str], str]:
    """Scan the licence texts of the SBOM's gap components; return
    (normalised name, version) -> detected SPDX expression."""
    gaps = {
        (normalize_name(c.get("name") or ""), c.get("version") or ""): c
        for c in sbom.get("components") or []
        if needs_detection(c)
    }
    stage = tempfile.mkdtemp(prefix="licence-texts-")
    try:
        staged = 0
        for key, component in gaps.items():
            for index, text in enumerate(embedded_texts(component)):
                with open(_stage(stage, key, f"sbom-licence-{index}.txt"), "w", encoding="utf-8") as handle:
                    handle.write(text)
                staged += 1
        if python:
            inventory = json.loads(
                subprocess.run([python, "-c", _INVENTORY], check=True,
                               capture_output=True, text=True).stdout
            )
            for dist in inventory:
                key = (normalize_name(dist["name"] or ""), dist["version"])
                if key not in gaps:
                    continue
                for rel, path in dist["files"]:
                    if is_license_file(rel) and os.path.isfile(path):
                        shutil.copyfile(path, _stage(stage, key, rel))
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

    mit = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
    cargo_unknown = {"license": {"name": "Unknown", "text": {
        "encoding": "base64", "content": base64.b64encode(mit.encode()).decode()}}}
    if not needs_detection({"licenses": [cargo_unknown]}):
        failures.append("  cargo 'Unknown' licence with embedded text is not a gap")
    if embedded_texts({"licenses": [cargo_unknown]}) != [mit]:
        failures.append(f"  embedded_texts(base64): {embedded_texts({'licenses': [cargo_unknown]})!r}")
    plain = {"license": {"name": "Unknown", "text": {"content": mit}}}
    if embedded_texts({"licenses": [plain]}) != [mit]:
        failures.append("  embedded_texts(plain) did not return the text")
    # A declared identifier is not a licence text to scan.
    if embedded_texts({"licenses": [declared_bsd]}):
        failures.append("  embedded_texts took a declared identifier as a licence text")
    if embedded_texts({"licenses": [{"license": {"id": "MIT"}}]}):
        failures.append("  embedded_texts returned text for an id entry")

    if failures:
        print("detect_licenses self-test FAILED:")
        print("\n".join(failures))
        return 1
    print(f"detect_licenses self-test passed ({len(cases) + len(files) + 11} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run the self-test and exit")
    parser.add_argument("sbom", nargs="?", help="CycloneDX JSON SBOM, updated in place")
    parser.add_argument("--python", help="Interpreter of the Python environment the SBOM describes")
    parser.add_argument("--scancode", help="scancode executable; without it the SBOM is unchanged")
    parser.add_argument(
        "--has-gaps", action="store_true",
        help="Exit 0 when some component needs detection, 1 when none does",
    )
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    if not args.sbom:
        parser.error("sbom is required unless --self-test is given")

    with open(args.sbom, encoding="utf-8") as handle:
        sbom = json.load(handle)
    gaps = [c for c in sbom.get("components") or [] if needs_detection(c)]
    if args.has_gaps:
        return 0 if gaps else 1
    if not gaps:
        return 0
    if not args.scancode:
        print(f"licence texts not scanned (no scancode): {len(gaps)} component(s) without a readable licence")
        return 0
    changed = apply_detections(sbom, detect(sbom, args.scancode, args.python))
    with open(args.sbom, "w", encoding="utf-8") as handle:
        json.dump(sbom, handle, indent=2)
        handle.write("\n")
    for line in changed:
        print(f"licence detected from its licence texts: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
