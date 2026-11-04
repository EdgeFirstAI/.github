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
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

from check_license_policy import (
    LINKAGE_PROPERTY,
    RANK_BLOCKED,
    RANK_REVIEW,
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


def apply_detections(
    sbom: dict,
    detections: Dict[Tuple[str, str], str],
    bundled: Optional[Dict[Tuple[str, str], List[dict]]] = None,
) -> List[str]:
    """Add each detected expression to the matching gap component, and the
    shared libraries it bundles as its nested components; return
    `name@version: expression` lines for the ones changed."""
    changed: List[str] = []
    for component in sbom.get("components") or []:
        name = component.get("name") or ""
        version = component.get("version") or ""
        key = (normalize_name(name), version)
        if not needs_detection(component):
            continue
        libraries = (bundled or {}).get(key) or []
        if libraries:
            component["components"] = list(component.get("components") or []) + libraries
            for library in libraries:
                changed.append(f"{name}@{version} bundles {library['name']} as a shared library")
        expression = detections.get(key)
        if not expression:
            continue
        # CycloneDX 1.5 `licenses` holds licence objects or exactly one
        # expression, never both. The detected expression becomes the
        # component's licence; what the metadata declared is kept as evidence,
        # as licence objects so that list stays valid too.
        original = [
            entry if "license" in entry else {"license": {"name": entry["expression"]}}
            for entry in component.get("licenses") or []
            if "license" in entry or "expression" in entry
        ]
        if original:
            evidence = component.setdefault("evidence", {})
            evidence["licenses"] = list(evidence.get("licenses") or []) + original
        component["licenses"] = [{"expression": expression}]
        changed.append(f"{name}@{version}: {expression}")
    return changed


# Run with the dependency environment's own interpreter: every installed
# distribution with the files of its .dist-info directory, and the paths of
# everything it installs.
_INVENTORY = """
import importlib.metadata as md, json, sys
out = []
for dist in md.distributions():
    files, installed = [], []
    for f in dist.files or []:
        rel = str(f)
        installed.append(rel)
        if rel.split("/")[0].endswith(".dist-info"):
            files.append([rel, str(dist.locate_file(f))])
    out.append({"name": dist.metadata["Name"], "version": dist.version,
                "files": files, "installed": installed})
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
    """Every licence file of a package applies, so their terms are ANDed. A
    plain AND chain is split into its terms first, so a licence found in two
    files is named once."""
    terms: List[str] = []
    for expression in expressions:
        if "(" in expression or re.search(r"\s(OR|WITH)\s", expression, re.IGNORECASE):
            terms.append(expression)
        else:
            terms.extend(part.strip() for part in re.split(r"\s+AND\s+", expression, flags=re.IGNORECASE))
    unique = list(dict.fromkeys(term for term in terms if term))
    if len(unique) == 1:
        return unique[0]
    return " AND ".join(f"({e})" if " " in e else e for e in unique)


# scancode matches that are not a licence: a pointer to one found elsewhere
# ("see LICENSE"), an introduction, a warranty disclaimer.
_NOT_A_LICENCE = {
    "licenseref-scancode-unknown-license-reference",
    "licenseref-scancode-warranty-disclaimer",
}
_CLUE_RULES = ("license-intro_", "license-clue_", "unknown-license-reference_")

# A match scoring below this is a phrase that resembles a licence, not one.
MIN_MATCH_SCORE = 80


def file_expression(entry: dict) -> Optional[str]:
    """The licences scancode found in one file, ANDed: every match except
    references, disclaimers and weak matches. A weak match still counts when
    it names a copyleft licence, so a doubtful GPL is never dropped."""
    found: List[str] = []
    for detection in entry.get("license_detections") or []:
        for item in detection.get("matches") or []:
            expression = (item.get("license_expression_spdx") or "").strip()
            rule = item.get("rule_identifier") or ""
            if not expression or expression.lower() in _NOT_A_LICENCE or rule.startswith(_CLUE_RULES):
                continue
            if float(item.get("score") or 0) < MIN_MATCH_SCORE:
                rank, _ = evaluate_expression(expression)
                if rank not in (RANK_BLOCKED, RANK_REVIEW):
                    continue
            found.append(expression)
    if not found:
        return None
    return combine(found)


_SHARED_LIBRARY = re.compile(r"\.(so(\.\d+)*|dylib|dll)$")
_EXTENSION_MODULE = re.compile(r"\.(cpython-|pypy|abi3\.)|\.pyd$")


def is_shared_library(path: str) -> bool:
    """A native library vendored as its own file: in the directory auditwheel
    or delvewheel creates (`<package>.libs/`) or delocate's (`.dylibs/`).
    Elsewhere a `.so` may be a Python extension module, the package's own
    compiled code, so it is not taken for a separate library."""
    parts = path.replace("\\", "/").split("/")
    vendored = any(part.endswith(".libs") or part == ".dylibs" for part in parts[:-1])
    name = parts[-1]
    return vendored and bool(_SHARED_LIBRARY.search(name)) and not _EXTENSION_MODULE.search(name)


_FIELD = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*)$")
_SEPARATOR = re.compile(r"^\s*[-=_*]{4,}\s*$")


def _bundled_sections(lines: List[str]) -> List[Tuple[int, int, Dict[str, str]]]:
    """(first line, end line, header fields) of each `Name:` section: the
    header fields, then its text up to the next section or separator line."""
    starts = [i for i, line in enumerate(lines) if line.startswith("Name:")]
    sections = []
    for index, start in enumerate(starts):
        limit = starts[index + 1] if index + 1 < len(starts) else len(lines)
        end = start + 1
        while end < limit and not _SEPARATOR.match(lines[end]):
            end += 1
        fields: Dict[str, str] = {}
        for line in lines[start:end]:
            field = _FIELD.match(line)
            if not field:
                break
            fields[field.group(1).lower()] = field.group(2).strip()
        sections.append((start, end, fields))
    return sections


def _installed_as(pattern: str, installed: List[str]) -> List[str]:
    """Installed files a `Files:` pattern names; a shared library's version
    suffix (libgfortran.so.5.0.0 for libgfortran*.so) is part of the name."""
    return [
        path for path in installed
        if fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, pattern + ".*")
    ]


_REFERENCED_TEXTS = re.compile(r"^\s*full text of licen[cs]e texts? referred to above", re.IGNORECASE)


def _referenced_texts(
    lines: List[str],
    sections: List[Tuple[int, int, Dict[str, str]]],
    dynamic_starts: set,
) -> set:
    """Lines of each "Full text of license texts referred to above follows"
    appendix whose referring libraries are all dynamic: from its separator to
    the next section. The referring libraries are the sections listed
    directly before it, back to the first one preceded by other text. If any
    of them is compiled in, the texts may be its terms and stay."""
    lines_moved: set = set()
    for start, end, _fields in sections:
        if end >= len(lines) or not _SEPARATOR.match(lines[end]):
            continue
        following = next((line for line in lines[end + 1:]
                          if line.strip() and not _SEPARATOR.match(line)), "")
        if not _REFERENCED_TEXTS.match(following):
            continue
        run = [start]
        previous = {s_end: s_start for s_start, s_end, _ in sections}
        while run[-1] in previous:
            run.append(previous[run[-1]])
        if not all(s in dynamic_starts for s in run):
            continue
        stop = next((s for s, _, _ in sections if s > end), len(lines))
        lines_moved.update(range(end, stop))
    return lines_moved


def split_bundled(text: str, installed: List[str]) -> Tuple[str, List[dict]]:
    """Split the libraries a package bundles as separate shared libraries
    out of its licence text.

    Wheels such as numpy's list each bundled library as a `Name:`/`Files:`/
    `License:` section. A section whose files are all installed, and are all
    shared libraries, describes a library loaded at run time: it becomes a
    component with that licence and `au-zone:linkage` "dynamic", and its text
    leaves the package's own licence. Anything else stays in the package's
    licence, so its terms apply to the package."""
    lines = text.splitlines(keepends=True)
    libraries: List[dict] = []
    moved = set()
    sections = _bundled_sections(lines)
    dynamic_starts = set()
    for start, end, fields in sections:
        licence = fields.get("license", "")
        patterns = fields.get("files", "").replace(",", " ").split()
        if not licence or not patterns:
            continue
        # Every pattern must name installed shared libraries and nothing else:
        # one naming a source file may describe code compiled in.
        matches = [_installed_as(pattern, installed) for pattern in patterns]
        if not all(found and all(is_shared_library(path) for path in found) for found in matches):
            continue
        files = [path for found in matches for path in found]
        dynamic_starts.add(start)
        libraries.append({
            "type": "library",
            "name": fields.get("name") or patterns[0],
            "licenses": [{"license": {"name": licence}}],
            "properties": [
                {"name": LINKAGE_PROPERTY, "value": "dynamic"},
                *({"name": "au-zone:files", "value": path} for path in sorted(set(files))),
            ],
        })
        moved.update(range(start, end))
    moved.update(_referenced_texts(lines, sections, dynamic_starts))
    if not libraries:
        return text, []
    return "".join(line for i, line in enumerate(lines) if i not in moved), libraries


def _stage(stage: str, key: Tuple[str, str], relative: str) -> str:
    target = os.path.join(stage, f"{key[0]}@{key[1]}", relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


def _read_file(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def licence_texts(
    gaps: Dict[Tuple[str, str], dict],
    inventory: List[dict],
    read=_read_file,
) -> Tuple[Dict[Tuple[str, str], List[Tuple[str, str]]], Dict[Tuple[str, str], List[dict]]]:
    """The licence texts to scan for each gap component, as (file name, text):
    those the SBOM embeds and the licence files its installed distribution
    ships, each with its bundled shared libraries split out (split_bundled).
    Also returns those libraries, each once per component."""
    installed = {
        (normalize_name(dist["name"] or ""), dist["version"]): dist.get("installed") or []
        for dist in inventory
    }
    texts: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
    bundled: Dict[Tuple[str, str], List[dict]] = {}

    def add(key: Tuple[str, str], relative: str, text: str) -> None:
        remaining, libraries = split_bundled(text, installed.get(key) or [])
        texts.setdefault(key, []).append((relative, remaining))
        known = bundled.setdefault(key, [])
        known.extend(library for library in libraries if library not in known)

    for key, component in gaps.items():
        for index, text in enumerate(embedded_texts(component)):
            add(key, f"sbom-licence-{index}.txt", text)
    for dist in inventory:
        key = (normalize_name(dist["name"] or ""), dist["version"])
        if key not in gaps:
            continue
        for relative, path in dist["files"]:
            if not is_license_file(relative):
                continue
            text = read(path)
            if text is not None:
                add(key, relative, text)
    return texts, {key: libraries for key, libraries in bundled.items() if libraries}


def detect(
    sbom: dict,
    scancode: str,
    python: Optional[str] = None,
) -> Tuple[Dict[Tuple[str, str], str], Dict[Tuple[str, str], List[dict]]]:
    """Scan the licence texts of the SBOM's gap components; return
    (normalised name, version) -> detected SPDX expression, and the same key
    -> the shared libraries that distribution bundles (see split_bundled)."""
    gaps = {
        (normalize_name(c.get("name") or ""), c.get("version") or ""): c
        for c in sbom.get("components") or []
        if needs_detection(c)
    }
    inventory: List[dict] = []
    if python:
        inventory = json.loads(
            subprocess.run([python, "-c", _INVENTORY], check=True,
                           capture_output=True, text=True).stdout
        )
    texts, bundled = licence_texts(gaps, inventory)
    stage = tempfile.mkdtemp(prefix="licence-texts-")
    try:
        staged = 0
        for key, items in texts.items():
            for relative, text in items:
                with open(_stage(stage, key, relative), "w", encoding="utf-8") as handle:
                    handle.write(text)
                staged += 1
        if not staged:
            return {}, bundled
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
            if entry.get("type") != "file":
                continue
            expression = file_expression(entry)
            if not expression:
                continue
            for part in entry["path"].split("/"):
                name, sep, version = part.partition("@")
                if sep and (name, version) in gaps:
                    found.setdefault((name, version), []).append(expression)
                    break
        return {key: combine(values) for key, values in found.items()}, bundled
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
    # CycloneDX 1.5 allows licence objects or exactly one expression, never
    # both: the detected expression replaces them, which move to evidence.
    if by_name["namex"].get("licenses") != [{"expression": "Apache-2.0"}]:
        failures.append(f"  namex: licenses {by_name['namex'].get('licenses')!r}")
    if by_name["Safe_Tensors"]["licenses"] != [{"expression": "Apache-2.0"}]:
        failures.append(f"  Safe_Tensors: licenses {by_name['Safe_Tensors']['licenses']!r}")
    if (by_name["Safe_Tensors"].get("evidence") or {}).get("licenses") != [classifier]:
        failures.append("  Safe_Tensors: original licence metadata not kept as evidence")
    if "evidence" in by_name["namex"]:
        failures.append("  namex: evidence added with no original licence metadata")
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

    checks = 0

    # What scancode reports for a vendor EULA that points at a second licence
    # file: references ("see LICENSE_APACHE"), disclaimers and weak phrase
    # matches are not licences, and decide nothing.
    def match(expression: str, score: float, rule: str) -> dict:
        return {"license_expression_spdx": expression, "score": score, "rule_identifier": rule}

    eula = {"matches": [
        match("Apache-2.0", 100, "apache-2.0_218.RULE"),
        match("LicenseRef-scancode-unknown-license-reference", 100, "unknown-license-reference_see-license_1.RULE"),
        match("LicenseRef-scancode-proprietary-license", 100, "proprietary-license_72.RULE"),
        match("LicenseRef-scancode-unknown-license-reference", 100, "license-intro_35.RULE"),
        match("LicenseRef-scancode-free-unknown", 50, "free-unknown_88.RULE"),
        match("LicenseRef-scancode-warranty-disclaimer", 100, "license-clue_warranty-disclaimer_1.RULE"),
        match("LicenseRef-scancode-proprietary-license", 100, "proprietary-license_72.RULE"),
    ]}
    expression_cases = [
        ({"license_detections": [eula]},
         "Apache-2.0 AND LicenseRef-scancode-proprietary-license"),
        # Nothing but references: no licence found, so the gap stays a gap.
        ({"license_detections": [{"matches": [
            match("LicenseRef-scancode-unknown-license-reference", 100, "unknown-license-reference_351.RULE")]}]},
         None),
        # A weak match still counts when it names a copyleft licence.
        ({"license_detections": [{"matches": [
            match("MIT", 100, "mit.LICENSE"), match("GPL-2.0-only", 50, "gpl-2.0_12.RULE")]}]},
         "MIT AND GPL-2.0-only"),
        ({}, None),
    ]
    for entry, expected in expression_cases:
        checks += 1
        got = file_expression(entry)
        if got != expected:
            failures.append(f"  file_expression: expected {expected!r}, got {got!r}")

    # numpy and scipy wheels list each bundled library with the files it
    # installs as. A library installed as a separate shared library is loaded
    # at run time, so it becomes its own component under its own licence; a
    # bundled source file is compiled in and stays in the package's licence.
    bundle = (
        "Copyright (c) 2005-2023, NumPy Developers.\nAll rights reserved.\n\n"
        "Name: lapack-lite\nFiles: numpy/linalg/lapack_lite/*\nLicense: BSD-3-Clause\n"
        "  For details, see numpy/linalg/lapack_lite/LICENSE.txt\n\n"
        "----\n\nThis binary distribution of NumPy also bundles the following software:\n\n\n"
        "Name: GCC runtime library\nFiles: numpy.libs/libgfortran*.so\n"
        "Description: dynamically linked to files compiled with gcc\n"
        "License: GPL-3.0-with-GCC-exception\n  GNU GENERAL PUBLIC LICENSE\n  Version 3\n\n"
        "----\n\nFull text of license texts referred to above follows (that they are\n"
        "listed below does not necessarily imply the conditions apply to the\n"
        "present binary release):\n\n----\n\n"
        "GPL FULL TEXT OF THE GCC RUNTIME\n\n----\n\nGCC RUNTIME LIBRARY EXCEPTION\n\n"
        "Name: libquadmath\nFiles: numpy.libs/libquadmath*.so\n"
        "License: LGPL-2.1-or-later\n  GNU LESSER GENERAL PUBLIC LICENSE\n\n"
        "Name: helper\nFiles: numpy/_helper.cpython-310-x86_64-linux-gnu.so\n"
        "License: LGPL-2.1-or-later\n  statically linked into the extension\n"
    )
    installed = [
        "numpy/__init__.py",
        "numpy/_helper.cpython-310-x86_64-linux-gnu.so",
        "numpy.libs/libgfortran-040039e1.so.5.0.0",
        "numpy.libs/libquadmath-96973f99.so.0.0.0",
    ]
    remaining, libraries = split_bundled(bundle, installed)
    checks += 1
    names = [c.get("name") for c in libraries]
    if names != ["GCC runtime library", "libquadmath"]:
        failures.append(f"  split_bundled: bundled libraries {names}")
    by_library = {c.get("name"): c for c in libraries}
    gcc = by_library.get("GCC runtime library") or {}
    if gcc.get("licenses") != [{"license": {"name": "GPL-3.0-with-GCC-exception"}}]:
        failures.append(f"  split_bundled: GCC runtime licences {gcc.get('licenses')!r}")
    if {"name": LINKAGE_PROPERTY, "value": "dynamic"} not in (gcc.get("properties") or []):
        failures.append(f"  split_bundled: GCC runtime properties {gcc.get('properties')!r}")
    if {"name": "au-zone:files", "value": "numpy.libs/libgfortran-040039e1.so.5.0.0"} not in (gcc.get("properties") or []):
        failures.append(f"  split_bundled: GCC runtime files {gcc.get('properties')!r}")
    for kept in ("NumPy Developers", "Name: lapack-lite", "Name: helper", "statically linked"):
        if kept not in remaining:
            failures.append(f"  split_bundled: dropped {kept!r} from the package's own licence")
    # The full texts "referred to above" belong to the libraries listed just
    # before them, which are all dynamic, so they leave with them.
    for moved in ("GNU GENERAL PUBLIC LICENSE", "GNU LESSER GENERAL PUBLIC LICENSE",
                  "GPL FULL TEXT OF THE GCC RUNTIME", "GCC RUNTIME LIBRARY EXCEPTION"):
        if moved in remaining:
            failures.append(f"  split_bundled: {moved!r} left in the package's own licence")
    # When a library listed just before those texts is compiled in, they may
    # be its terms, so they stay in the package's licence.
    checks += 1
    compiled_in = bundle.replace(
        "Name: GCC runtime library\nFiles: numpy.libs/libgfortran*.so",
        "Name: libquadmath-src\nFiles: numpy/_quad.c\nLicense: LGPL-2.1-or-later\n\n"
        "Name: GCC runtime library\nFiles: numpy.libs/libgfortran*.so")
    kept_text, _ = split_bundled(compiled_in, installed)
    if "GPL FULL TEXT OF THE GCC RUNTIME" not in kept_text:
        failures.append("  split_bundled: moved licence texts a compiled-in library may refer to")

    checks += 1
    flat = combine(["Apache-2.0 AND LicenseRef-scancode-proprietary-license", "Apache-2.0"])
    if flat != "Apache-2.0 AND LicenseRef-scancode-proprietary-license":
        failures.append(f"  combine: repeated AND terms kept: {flat!r}")
    checks += 1
    if combine(["MIT", "Apache-2.0 OR MIT"]) != "MIT AND (Apache-2.0 OR MIT)":
        failures.append(f"  combine: {combine(['MIT', 'Apache-2.0 OR MIT'])!r}")
    # A section whose files are not installed is not shown to be dynamic.
    checks += 1
    if split_bundled(bundle, ["numpy/__init__.py"]) != (bundle, []):
        failures.append("  split_bundled: moved a section with no installed shared library")
    # A section that also names files not installed as shared libraries, such
    # as a source file compiled into an extension, is not shown to be dynamic.
    checks += 1
    mixed = bundle.replace("Files: numpy.libs/libquadmath*.so", "Files: numpy.libs/libquadmath*.so numpy/_quad.c")
    _, mixed_libraries = split_bundled(mixed, installed)
    if "libquadmath" in [c["name"] for c in mixed_libraries]:
        failures.append("  split_bundled: moved a section that also names a compiled-in source file")

    shared = [
        ("numpy.libs/libgfortran-040039e1.so.5.0.0", True),
        ("scipy.libs/libopenblasp-r0-23e5df77.3.21.dev.so", True),
        ("PIL/.dylibs/libjpeg.62.dylib", True),
        ("numpy.libs/libopenblas.dll", True),
        ("numpy/core/_multiarray_umath.cpython-310-x86_64-linux-gnu.so", False),
        ("foo/_ext.abi3.so", False),
        ("foo/_ext.pyd", False),
        ("foo/module.py", False),
        # An untagged .so can be an extension module; only a vendoring
        # directory shows a library was installed as its own file.
        ("pkg/_helper.so", False),
        ("pkg/libfoo.so.1", False),
    ]
    for path, expected in shared:
        checks += 1
        if is_shared_library(path) != expected:
            failures.append(f"  is_shared_library({path!r}): expected {expected}")

    # cyclonedx-py embeds the same licence text in the SBOM that the
    # distribution installs: both copies are split, and each library is
    # recorded once.
    checks += 1
    embedded = {"license": {"name": "declared license of 'numpy'", "text": {"content": bundle}}}
    gap = {"name": "numpy", "version": "1.26.4", "licenses": [classifier, embedded]}
    texts, found_libraries = licence_texts(
        {("numpy", "1.26.4"): gap},
        [{"name": "numpy", "version": "1.26.4", "installed": installed,
          "files": [["numpy-1.26.4.dist-info/LICENSE.txt", bundle]]}],
        read=lambda content: content,
    )
    staged_texts = [text for _, text in texts.get(("numpy", "1.26.4"), [])]
    if len(staged_texts) != 2 or any("GPL FULL TEXT OF THE GCC RUNTIME" in t for t in staged_texts):
        failures.append(f"  licence_texts: {len(staged_texts)} texts, bundled licence texts left in")
    staged_names = [c["name"] for c in found_libraries.get(("numpy", "1.26.4"), [])]
    if staged_names != ["GCC runtime library", "libquadmath"]:
        failures.append(f"  licence_texts: bundled libraries {staged_names}")

    sbom = {"components": [{"name": "numpy", "version": "1.26.4", "licenses": [classifier]}]}
    apply_detections(sbom, {("numpy", "1.26.4"): "BSD-3-Clause"},
                     {("numpy", "1.26.4"): libraries})
    checks += 1
    nested = [c.get("name") for c in sbom["components"][0].get("components") or []]
    if nested != ["GCC runtime library", "libquadmath"]:
        failures.append(f"  apply_detections: bundled libraries {nested}")

    if failures:
        print("detect_licenses self-test FAILED:")
        print("\n".join(failures))
        return 1
    print(f"detect_licenses self-test passed ({len(cases) + len(files) + 13 + checks} cases)")
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
    detections, bundled = detect(sbom, args.scancode, args.python)
    changed = apply_detections(sbom, detections, bundled)
    with open(args.sbom, "w", encoding="utf-8") as handle:
        json.dump(sbom, handle, indent=2)
        handle.write("\n")
    for line in changed:
        print(f"licence detected from its licence texts: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
