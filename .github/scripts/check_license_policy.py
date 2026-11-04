#!/usr/bin/env python3
"""Check CycloneDX SBOM license policy (Au-Zone SPS).

Policy version: 2.3 (2026-11-04). This is the single org-wide copy.

Exit 0 when every component is allowed, or proprietary and approved for
this repository.
Exit 1 on blocked licenses, LGPL in Rust, or unapproved proprietary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Dict, Iterable, List, Optional, Set, Tuple

ALLOWED_LICENSES: Set[str] = {
    "MIT",
    "MIT-0",
    "Apache-2.0",
    "Apache-2.0 WITH LLVM-exception",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "NCSA",
    "0BSD",
    "Unlicense",
    "Zlib",
    "BSL-1.0",
    "Unicode-3.0",
    "Unicode-DFS-2016",
    "LLVM-exception",
    "CDLA-Permissive-2.0",
    "CC0-1.0",
    "CC-BY-4.0",
    "OFL-1.1",
    "Ubuntu-font-1.0",
    "MPL-2.0",
    "BlueOak-1.0.0",
    "OpenSSL",
    "IJG",
    "IJG-short",
    "WTFPL",
    "PSF-2.0",
    "Python-2.0",
    "MIT-CMU",
    "BSD-3-Clause-Attribution",
    "TCL",
}

# Composite expressions ("MIT OR Apache-2.0", "(MIT OR Apache-2.0) AND IJG")
# are not listed here. evaluate_expression parses them and resolves each leaf
# against this set, so only single license identifiers belong above.

REVIEW_REQUIRED_LICENSES: Set[str] = {
    "LGPL-2.1",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
}

BLOCKED_LICENSES: Set[str] = {
    "GPL-2.0",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "AGPL-3.0",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "SSPL-1.0",
}

CONDITIONAL_PROPRIETARY_LICENSES: Set[str] = {
    "NXP Proprietary",
    "NXP-Proprietary",
    "LA_OPT_NXP_SW",
    "LA_OPT_NXP_Software_License",
}

# Licences are approved by SPDX identifier, never per package or version. A
# component whose metadata hides its licence is resolved from its own licence
# texts by detect_licenses.py before this check runs.

DEFAULT_DYNAMIC: Set[str] = {"gstreamer", "glib", "libglib"}

# CycloneDX property detect_licenses.py sets to "dynamic" on a library a
# package bundles as a separate shared library, loaded at run time rather than
# linked into the package's own code.
LINKAGE_PROPERTY = "au-zone:linkage"


def _split_csv(value: str) -> Set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def dynamic_libraries() -> Set[str]:
    extra = os.environ.get("DYNAMICALLY_LINKED_LIBRARIES", "")
    names = set(DEFAULT_DYNAMIC)
    names.update(_split_csv(extra))
    return {name.lower() for name in names}


def is_rust_project() -> bool:
    language = os.environ.get("PROJECT_LANGUAGE", "").lower()
    if language:
        return language == "rust"
    return os.path.exists("Cargo.toml")


def normalize_license(raw: str) -> str:
    text = raw.strip()
    aliases = {
        "Apache 2.0": "Apache-2.0",
        "Apache License 2.0": "Apache-2.0",
        "The MIT License": "MIT",
        "MIT License": "MIT",
        "BSD-3-Clause-Clear": "BSD-3-Clause",
        "3-Clause BSD License": "BSD-3-Clause",
        "BSD 3-Clause": "BSD-3-Clause",
        "BSD 3-Clause License": "BSD-3-Clause",
        "BSD 2-Clause License": "BSD-2-Clause",
    }
    return aliases.get(text, text)


# cyclonedx-py names a Python package's free-text `License:` metadata field
# "declared license of '<package>'" and carries the field in its text.
DECLARED_LICENSE_PREFIX = "declared license of "


def licence_document_digest(text: str) -> str:
    """SHA-256 of a licence text with its whitespace collapsed, so the same
    text reflowed or re-indented by packaging tools has one digest."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


# Whole licence texts the organisation has reviewed, by
# licence_document_digest: what each document is, and the SPDX licences of
# its parts, which the policy then judges like any declared expression. A
# package that pastes a combined licence into its `License:` field (its own
# terms followed by those of the code it bundles) is read through here and
# nowhere else; a text not listed is left to detection. Any change to the text
# is a new document needing its own review.
KNOWN_LICENCE_DOCUMENTS: Dict[str, dict] = {
    "6b0048fbb0e250e1ab550b67fdb5ef98c942d1deeb6ed85dc5894777d913b2f7": {
        "document": (
            "pandas LICENSE: pandas BSD-3-Clause, with bottleneck (BSD-2-Clause), "
            "dateutil (Apache-2.0, BSD-3-Clause), klib (MIT), musl (MIT), the Python "
            "licence stack (Python-2.0), ujson/MODP (BSD-3-Clause), a 0BSD notice and "
            "the TCL numeric decoder (TCL). Its Python licence footnotes mention the "
            "GPL only to compare licences."
        ),
        "expression": "BSD-3-Clause AND BSD-2-Clause AND Apache-2.0 AND MIT AND Python-2.0 AND 0BSD AND TCL",
        "approved-by": "Sébastien Taylor",
        "date": "2026-11-04",
    },
}


def declared_license(
    license_obj: dict,
    documents: Optional[Dict[str, dict]] = None,
) -> Optional[str]:
    """The identifier in a declared-licence entry's text, or the expression of
    a reviewed licence document (KNOWN_LICENCE_DOCUMENTS); None for any other
    whole licence text, which is left to detection."""
    text = (license_obj.get("text") or {}).get("content") or ""
    text = text.strip()
    if "\n" in text or len(text) > 64:
        known = (KNOWN_LICENCE_DOCUMENTS if documents is None else documents).get(
            licence_document_digest(text))
        return known["expression"] if known else None
    if not text:
        return None
    return text


def licenses_from_component(component: dict) -> List[str]:
    found: List[str] = []
    for entry in component.get("licenses") or []:
        license_obj = entry.get("license") or {}
        if "id" in license_obj:
            found.append(normalize_license(license_obj["id"]))
        elif str(license_obj.get("name", "")).startswith(DECLARED_LICENSE_PREFIX):
            declared = declared_license(license_obj)
            if declared:
                found.append(normalize_license(declared))
        elif "name" in license_obj:
            found.append(normalize_license(license_obj["name"]))
        elif "expression" in entry:
            found.append(normalize_license(entry["expression"]))
    return found


def component_key(component: dict) -> str:
    name = component.get("name") or "unknown"
    version = component.get("version") or ""
    return f"{name}@{version}" if version else name


# Proprietary licences are never accepted organisation-wide (SPS-01 Category
# C, approval required). A repository that genuinely needs one records the
# approval of each package here, where its reviewers see it. An approval
# covers the package at any version, for the licence it names.
APPROVALS_FILE = ".github/license-approvals.json"
APPROVAL_FIELDS = ("license", "approved-by", "date", "justification")


def package_key(name: str) -> str:
    """A package name as its registry compares it: case and the -, _ and .
    separators do not distinguish Python distributions or crates."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_approvals(data: object, source: str) -> Dict[str, dict]:
    """Validated approvals: package name -> the signed record of one
    proprietary dependency. Anything malformed stops the check."""
    if not isinstance(data, dict):
        raise SystemExit(f"{source}: approvals must be a JSON object")
    approvals: Dict[str, dict] = {}
    for key, record in data.items():
        if not str(key).strip() or "@" in str(key):
            raise SystemExit(
                f"{source}: {key!r} must be a package name; approvals are per "
                "package, not per version"
            )
        if not isinstance(record, dict):
            raise SystemExit(f"{source}: {key} must be an object of {', '.join(APPROVAL_FIELDS)}")
        for field in APPROVAL_FIELDS:
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SystemExit(f"{source}: {key} needs a non-empty {field!r}")
        approvals[package_key(str(key))] = record
    return approvals


def load_approvals(path: Optional[str]) -> Dict[str, dict]:
    """The repository's approvals: `path` when given (and then required),
    otherwise APPROVALS_FILE when it exists."""
    if not path:
        if not os.path.exists(APPROVALS_FILE):
            return {}
        path = APPROVALS_FILE
    with open(path, encoding="utf-8") as handle:
        return parse_approvals(json.load(handle), path)


# Outcome ranks, best to worst. AND takes the worst operand because every term
# binds; OR takes the best because we may rely on a single branch.
RANK_ALLOWED = 0
RANK_PROPRIETARY = 1
RANK_REVIEW = 2
RANK_UNKNOWN = 3
RANK_BLOCKED = 4


def tokenize_expression(expression: str) -> List[str]:
    """Split an SPDX expression into parens, operators, and license leaves."""
    tokens: List[str] = []
    buffer: List[str] = []

    def flush() -> None:
        if buffer:
            token = "".join(buffer).strip()
            if token:
                tokens.append(token)
            buffer.clear()

    index = 0
    while index < len(expression):
        char = expression[index]
        if char in "()":
            flush()
            tokens.append(char)
            index += 1
            continue
        matched = False
        # Operators are case-insensitive in SPDX and stand apart from
        # identifiers: whitespace or a parenthesis on each side. "-" and "."
        # are identifier characters, so "GPL-3.0-or-later" is one leaf, and
        # "ORACLE" and "SAND" are never read as operators.
        for operator in ("AND", "OR", "WITH"):
            end = index + len(operator)
            if (
                expression[index:end].upper() == operator
                and (index == 0 or expression[index - 1].isspace()
                     or expression[index - 1] in "()")
                and (end >= len(expression) or expression[end].isspace()
                     or expression[end] in "()")
            ):
                if operator == "WITH":
                    # WITH binds tighter than AND/OR: keep the exception with
                    # its license so "Apache-2.0 WITH LLVM-exception" stays a
                    # single allowlist lookup.
                    buffer.append(expression[index:end])
                else:
                    flush()
                    tokens.append(operator)
                index = end
                matched = True
                break
        if not matched:
            buffer.append(char)
            index += 1
    flush()
    return tokens


def _normalize_leaf(leaf: str) -> str:
    # A trailing "+" means "or later"; policy treats both the same.
    return normalize_license(leaf.rstrip("+").strip())


def _lower(values: Set[str]) -> Set[str]:
    return {value.lower() for value in values}


# SPDX identifiers are case-insensitive. Matching on the canonical casing alone
# let "gpl-3.0" slip past the blocked check and land in UNKNOWN.
_ALLOWED_LOWER = _lower(ALLOWED_LICENSES)
_BLOCKED_LOWER = _lower(BLOCKED_LICENSES)
_REVIEW_LOWER = _lower(REVIEW_REQUIRED_LICENSES)
_PROPRIETARY_LOWER = _lower(CONDITIONAL_PROPRIETARY_LICENSES)


# SPDX's deprecated single identifiers for GPL with the GCC runtime exception.
_DEPRECATED_GCC_EXCEPTION = {
    "gpl-2.0-with-gcc-exception": "GPL-2.0-only WITH GCC-exception-2.0",
    "gpl-3.0-with-gcc-exception": "GPL-3.0-only WITH GCC-exception-3.1",
}

_WITH = re.compile(r"\s+with\s+", re.IGNORECASE)


def is_gcc_runtime_exception(license_id: str) -> bool:
    """GPL with the GCC runtime library exception: the licence of the GCC
    runtime (libgcc, libgfortran, libstdc++), which lets independent code use
    the library under its own terms."""
    folded = _DEPRECATED_GCC_EXCEPTION.get(license_id.lower(), license_id).lower()
    parts = _WITH.split(folded)
    return (
        len(parts) == 2
        and parts[0].startswith("gpl-")
        and parts[1].startswith("gcc-exception-")
    )


def classify_leaf(leaf: str) -> Tuple[int, str]:
    license_id = _normalize_leaf(leaf)
    if not license_id:
        return RANK_UNKNOWN, "UNKNOWN"
    folded = license_id.lower()
    # Held to the LGPL rule: allowed only as a dynamically loaded library.
    if is_gcc_runtime_exception(license_id):
        return RANK_REVIEW, license_id
    if (
        folded in _BLOCKED_LOWER
        or folded.startswith("gpl")
        or folded.startswith("agpl")
    ):
        return RANK_BLOCKED, license_id
    if folded in _REVIEW_LOWER or folded.startswith("lgpl"):
        return RANK_REVIEW, license_id
    if folded in _PROPRIETARY_LOWER or "proprietary" in folded:
        return RANK_PROPRIETARY, license_id
    if folded in _ALLOWED_LOWER:
        return RANK_ALLOWED, license_id
    return RANK_UNKNOWN, license_id


def evaluate_expression(expression: str) -> Tuple[int, str]:
    """Resolve an SPDX expression to its (rank, license) outcome.

    Handles nesting and parentheses, so "(MIT OR Apache-2.0) AND IJG" is the
    worst of best-of-{MIT, Apache-2.0} and IJG, rather than an unmatched string
    compare of the whole expression against the allowlist.
    """
    tokens = tokenize_expression(expression)
    if not tokens:
        return RANK_UNKNOWN, "UNKNOWN"

    position = 0

    def advance() -> None:
        nonlocal position
        position += 1

    def parse_atom() -> Tuple[int, str]:
        if position >= len(tokens):
            return RANK_UNKNOWN, "UNKNOWN"
        token = tokens[position]
        if token == "(":
            advance()
            rank, license_id = parse_or()
            if position < len(tokens) and tokens[position] == ")":
                advance()
            return rank, license_id
        if token in ("AND", "OR", ")"):
            # Malformed expression; never treat it as permissive.
            advance()
            return RANK_UNKNOWN, "UNKNOWN"
        advance()
        return classify_leaf(token)

    def parse_and() -> Tuple[int, str]:
        rank, license_id = parse_atom()
        while position < len(tokens) and tokens[position] == "AND":
            advance()
            right_rank, right_license = parse_atom()
            if right_rank > rank:
                rank, license_id = right_rank, right_license
        return rank, license_id

    def parse_or() -> Tuple[int, str]:
        rank, license_id = parse_and()
        while position < len(tokens) and tokens[position] == "OR":
            advance()
            right_rank, right_license = parse_and()
            if right_rank < rank:
                rank, license_id = right_rank, right_license
        return rank, license_id

    rank, license_id = parse_or()
    if position < len(tokens):
        # Trailing tokens mean we did not understand the expression.
        return RANK_UNKNOWN, expression
    return rank, license_id


def _same_expression(a: str, b: str) -> bool:
    """Equal licence declarations, ignoring case and spacing."""
    return " ".join(a.split()).lower() == " ".join(b.split()).lower()


def evaluate_component(
    component: dict,
    rust: bool,
    dynamic: Set[str],
    approvals: Optional[Dict[str, dict]] = None,
) -> Tuple[str, str, str]:
    """Return (status, license, detail) status in {ok, warn, fail}."""
    key = component_key(component)
    name = (component.get("name") or "").lower()
    licenses = licenses_from_component(component)
    if not licenses:
        return "fail", "UNKNOWN", f"{key}: missing license metadata"

    # Multiple license entries on one component are alternatives, so the best
    # outcome wins, matching OR. Seed from the first entry rather than a
    # constant, so the reported id is always the leaf that decided the verdict.
    best_rank, best_license = evaluate_expression(licenses[0])
    best_expression = licenses[0]
    for expression in licenses[1:]:
        if best_rank == RANK_ALLOWED:
            break
        rank, license_id = evaluate_expression(expression)
        if rank < best_rank:
            best_rank, best_license = rank, license_id
            best_expression = expression

    if best_rank == RANK_ALLOWED:
        return "ok", best_license, f"{key}: {best_license}"
    if best_rank == RANK_PROPRIETARY:
        approval = (approvals or {}).get(package_key(component.get("name") or ""))
        if not approval:
            return "fail", best_license, (
                f"{key}: proprietary {best_license} is not approved for this "
                f"repository ({APPROVALS_FILE})"
            )
        # The approval names the whole declaration that decided the verdict,
        # so a further licence ANDed into it is never covered by an approval
        # of one of its terms.
        if not _same_expression(approval["license"], best_expression):
            return "fail", best_license, (
                f"{key}: approved as {approval['license']}, but the SBOM "
                f"declares {best_expression}"
            )
        return "warn", best_license, (
            f"{key}: proprietary {best_license} approved by "
            f"{approval['approved-by']} on {approval['date']}; NOTICE must name it"
        )
    if best_rank == RANK_REVIEW:
        # LGPL, and GPL with the GCC runtime exception, are allowed only for
        # a library loaded dynamically: one the repository documents as such,
        # or one detect_licenses.py found bundled as a separate shared library.
        if rust:
            return "fail", best_license, (
                f"{key}: {best_license} is forbidden in Rust "
                "(static linking cannot satisfy it)"
            )
        linkage = {
            str(prop.get("value", "")).lower()
            for prop in component.get("properties") or []
            if prop.get("name") == LINKAGE_PROPERTY
        }
        documented = name.split("-")[0] in dynamic or name in dynamic
        if not documented and linkage != {"dynamic"}:
            return "fail", best_license, (
                f"{key}: {best_license} allowed only for dynamically linked "
                "libraries"
            )
        return "warn", best_license, f"{key}: permitted as dynamic {best_license}"
    if best_rank == RANK_BLOCKED:
        return "fail", best_license, f"{key}: blocked license {best_license}"
    return "fail", best_license, (
        f"{key}: license {best_license} is not on the allowed list"
    )


def _with_nested(components: Iterable[dict]) -> Iterable[dict]:
    for component in components:
        yield component
        yield from _with_nested(component.get("components") or [])


def iter_components(sbom: dict) -> Iterable[dict]:
    """Every component, including those nested in another: a library bundled
    inside a package is checked under its own licence."""
    yield from _with_nested(sbom.get("components") or [])
    metadata = sbom.get("metadata") or {}
    component = metadata.get("component")
    if component:
        yield from _with_nested(component.get("components") or [])


# Cases that have actually broken the fleet, plus the operator semantics the
# evaluator has to preserve. Run by the shared CI lint job.
SELF_TEST_CASES = [
    # (expression, rust project, expected status)
    # cargo-cyclonedx emits parenthesised compounds; these two failed hal Quick
    # when the evaluator was a flat string compare (EDGEAI-1554).
    ("(MIT OR Apache-2.0) AND IJG", True, "ok"),
    ("(MIT OR Apache-2.0) AND Unicode-3.0", True, "ok"),
    ("MIT OR Apache-2.0", True, "ok"),
    ("MIT AND Apache-2.0", True, "ok"),
    ("Apache-2.0 WITH LLVM-exception", True, "ok"),
    ("MIT", True, "ok"),
    ("WTFPL", True, "ok"),
    ("MIT+", True, "ok"),
    ("mit or apache-2.0", True, "ok"),
    # Case-insensitivity is asserted on the BLOCKED side, not only the allowed
    # side. A case-sensitive compare does not merely mis-sort a lower-case
    # blocked identifier -- it fails to recognise it at all, so `gpl-3.0`
    # sailed past the blocked list while `GPL-3.0` was caught. cargo-cyclonedx
    # and scancode both emit identifiers as the upstream metadata wrote them,
    # so casing is never ours to assume. Every blocked family is pinned here
    # in lower and mixed case.
    ("gpl-3.0", True, "fail"),
    ("GpL-3.0", True, "fail"),
    ("gpl-2.0-only", True, "fail"),
    ("mit and gpl-3.0", True, "fail"),
    ("agpl-3.0", True, "fail"),
    ("sspl-1.0", True, "fail"),
    ("lgpl-2.1", True, "fail"),
    ("apache-2.0 with llvm-exception", True, "ok"),
    # AND takes the worst operand: one blocked term poisons the whole grant.
    ("MIT AND GPL-3.0", True, "fail"),
    ("(MIT OR Apache-2.0) AND GPL-3.0", True, "fail"),
    # OR takes the best: a permissive branch rescues a blocked one.
    ("GPL-3.0 OR MIT", True, "ok"),
    ("GPL-2.0-only", True, "fail"),
    ("AGPL-3.0", True, "fail"),
    ("SSPL-1.0", True, "fail"),
    # Unknown identifiers must never pass, alone or under AND.
    ("NotARealLicense", True, "fail"),
    ("MIT AND NotARealLicense", True, "fail"),
    ("MIT OR NotARealLicense", True, "ok"),
    # LGPL stays forbidden in Rust and undocumented-dynamic elsewhere.
    ("LGPL-2.1", True, "fail"),
    ("LGPL-2.1", False, "fail"),
    ("(MIT OR LGPL-3.0) AND MIT", True, "ok"),
    # Malformed input fails closed.
    ("", True, "fail"),
    ("MIT AND", True, "fail"),
    ("(MIT OR Apache-2.0", True, "ok"),
    # typing_extensions and anything carrying CPython code.
    ("PSF-2.0", False, "ok"),
    ("BSD-3-Clause AND PSF-2.0", False, "ok"),
    ("Python-2.0", False, "ok"),
    # Pillow's declared licence.
    ("MIT-CMU", False, "ok"),
    # OpenBLAS and LAPACK, as numpy and scipy wheels bundle them.
    ("BSD-3-Clause-Attribution", False, "ok"),
    # The TCL licence of the numeric decoder pandas bundles.
    ("TCL", False, "ok"),
    # "or" inside an identifier is not the OR operator: GPL-3.0-or-later must
    # stay one blocked leaf, never "GPL-3.0 OR later".
    ("GPL-3.0-or-later", False, "fail"),
    ("MIT AND LGPL-2.1-or-later", False, "fail"),
    ("BSD-3-Clause AND MIT-CMU", False, "ok"),
    # GPL with a GCC runtime exception is held to the LGPL rule: only as a
    # dynamically loaded library, never in Rust, never in an undocumented
    # component. Any other exception leaves plain GPL.
    ("GPL-3.0-or-later WITH GCC-exception-3.1", False, "fail"),
    ("GPL-3.0-or-later WITH GCC-exception-3.1", True, "fail"),
    ("GPL-2.0-only WITH Classpath-exception-2.0", False, "fail"),
]


def _declared(text: str) -> dict:
    """A licence entry as cyclonedx-py --gather-license-texts writes a
    package's free-text `License:` metadata field."""
    return {"license": {"name": "declared license of 'probe'", "text": {"content": text}}}


_CLASSIFIER = {"license": {"name": "License :: OSI Approved :: Apache Software License"}}

# Whole components, for what the expression cases cannot reach: which licence
# entries are read.
COMPONENT_CASES = [
    # (name, version, licenses, expected status)
    ("probe", "0.0.0", [_declared("Apache License 2.0")], "ok"),
    ("probe", "0.0.0", [_declared("3-Clause BSD License")], "ok"),
    ("probe", "0.0.0", [_declared("BSD 3-Clause")], "ok"),
    # pandas declares this.
    ("probe", "0.0.0", [_declared("BSD 3-Clause License")], "ok"),
    ("probe", "0.0.0", [_declared("BSD 2-Clause License")], "ok"),
    ("probe", "0.0.0", [_CLASSIFIER, _declared("Apache 2.0")], "ok"),
    # Declared text is classified like any identifier, never trusted.
    ("probe", "0.0.0", [_declared("GPL-3.0")], "fail"),
    ("probe", "0.0.0", [_declared("BSD")], "fail"),
    # A whole licence pasted into the field is not an identifier, title line
    # included: the text can carry further terms after it, as pandas' carries
    # the licences of the code it bundles. Only a licence document the
    # organisation has reviewed is read (see the KNOWN_LICENCE_DOCUMENTS cases).
    ("probe", "0.0.0", [_declared("MIT\n\nPermission is hereby granted...")], "fail"),
    ("probe", "0.0.0", [_declared("BSD 3-Clause License\n\nCopyright (c) 2008-2011, AQR")], "fail"),
    ("probe", "0.0.0", [_declared("Copyright (c) 2005-2023, NumPy Developers.\nAll rights reserved.")], "fail"),
    ("probe", "0.0.0", [_CLASSIFIER], "fail"),
    # What detect_licenses.py adds from a component's licence texts.
    ("probe", "0.0.0", [_CLASSIFIER, {"expression": "Apache-2.0"}], "ok"),
    ("probe", "0.0.0", [_declared("BSD"), {"expression": "BSD-3-Clause AND Python-2.0"}], "ok"),
]

_APPROVAL = {
    "license": "NXP Proprietary",
    "approved-by": "Approver Name",
    "date": "2026-11-03",
    "justification": "i.MX 95 runtime; no open alternative",
}
_NXP_DECLARED = [_declared("NXP Proprietary")]
_NXP_ID = [{"license": {"id": "LA_OPT_NXP_SW"}}]

# Proprietary components pass only with this repository's approval of that
# package and licence, at any version, and are then still named in NOTICE
# (warn).
APPROVAL_CASES = [
    # (name, version, licenses, approvals, expected status)
    ("vendor-sdk", "1.0.0", _NXP_DECLARED, {}, "fail"),
    ("vendor-sdk", "1.0.0", _NXP_ID, {}, "fail"),
    ("vendor-sdk", "1.0.0", [{"license": {"name": "Some Proprietary EULA"}}], {}, "fail"),
    ("vendor-sdk", "1.0.0", _NXP_DECLARED, {"vendor-sdk": _APPROVAL}, "warn"),
    ("vendor-sdk", "2.3.1", _NXP_DECLARED, {"vendor-sdk": _APPROVAL}, "warn"),
    # Python and crate names compare like their registries do.
    ("Vendor_SDK", "1.0.0", _NXP_DECLARED, {"vendor-sdk": _APPROVAL}, "warn"),
    ("other-sdk", "1.0.0", _NXP_DECLARED, {"vendor-sdk": _APPROVAL}, "fail"),
    # A licence other than the one approved needs its own approval.
    ("vendor-sdk", "1.0.0", _NXP_ID, {"vendor-sdk": _APPROVAL}, "fail"),
    # An approval covers the whole declaration, never one leaf of it: a second
    # proprietary licence ANDed in needs the approval to name both.
    ("vendor-sdk", "1.0.0", [{"expression": "NXP Proprietary AND Vendor Proprietary EULA"}],
     {"vendor-sdk": _APPROVAL}, "fail"),
    ("vendor-sdk", "1.0.0", [{"expression": "NXP Proprietary AND Vendor Proprietary EULA"}],
     {"vendor-sdk": dict(_APPROVAL, license="NXP Proprietary AND Vendor Proprietary EULA")}, "warn"),
    # A vendor EULA as detection reads it: the permissive licence of a part
    # never makes the whole permissive, so the package still needs approval.
    ("vendor-sdk", "1.0.0", [{"expression": "Apache-2.0 AND LicenseRef-scancode-proprietary-license"}],
     {}, "fail"),
    ("vendor-sdk", "1.0.0", [{"expression": "Apache-2.0 AND LicenseRef-scancode-proprietary-license"}],
     {"vendor-sdk": dict(_APPROVAL, license="Apache-2.0 AND LicenseRef-scancode-proprietary-license")},
     "warn"),
    # An approval never rescues a licence outside the proprietary rank.
    ("vendor-sdk", "1.0.0", [{"license": {"id": "GPL-3.0"}}],
     {"vendor-sdk": dict(_APPROVAL, license="GPL-3.0")}, "fail"),
]

# (expression, linkage property, rust project, expected status)
BUNDLED_CASES = [
    ("LGPL-2.1-or-later", "dynamic", False, "warn"),
    ("GPL-3.0-or-later WITH GCC-exception-3.1", "dynamic", False, "warn"),
    ("GPL-3.0-with-GCC-exception", "dynamic", False, "warn"),
    ("BSD-3-Clause", "dynamic", False, "ok"),
    # Static, or linkage not established: the copyleft terms reach the package.
    ("LGPL-2.1-or-later", "static", False, "fail"),
    ("LGPL-2.1-or-later", None, False, "fail"),
    ("GPL-3.0-or-later WITH GCC-exception-3.1", None, False, "fail"),
    # Only the GCC runtime exception: plain GPL stays blocked when dynamic.
    ("GPL-3.0-or-later", "dynamic", False, "fail"),
    ("GPL-2.0-only WITH Classpath-exception-2.0", "dynamic", False, "fail"),
    # Rust links statically.
    ("LGPL-2.1-or-later", "dynamic", True, "fail"),
]

# Approval entries that must be refused: each field is the record a reviewer
# signs, so none may be missing or empty.
INVALID_APPROVALS = [
    [],
    {"vendor-sdk@1.0.0": "NXP Proprietary"},
    {"vendor-sdk@1.0.0": {k: v for k, v in _APPROVAL.items() if k != "approved-by"}},
    {"vendor-sdk@1.0.0": dict(_APPROVAL, justification=" ")},
    # Approvals are per package, never per version.
    {"vendor-sdk@1.0.0": _APPROVAL},
]


def run_self_test() -> int:
    failures = []
    for name, version, licenses, expected in COMPONENT_CASES:
        component = {"name": name, "version": version, "licenses": licenses}
        status, license_id, detail = evaluate_component(
            component, False, set(DEFAULT_DYNAMIC)
        )
        if status != expected:
            failures.append(
                f"  {name}@{version} {licenses!r}: expected {expected}, got "
                f"{status} [{license_id}] {detail}"
            )
    for name, version, licenses, approvals, expected in APPROVAL_CASES:
        component = {"name": name, "version": version, "licenses": licenses}
        status, license_id, detail = evaluate_component(
            component, False, set(DEFAULT_DYNAMIC),
            parse_approvals(approvals, "self-test"),
        )
        if status != expected:
            failures.append(
                f"  {name}@{version} approvals={sorted(approvals)}: expected "
                f"{expected}, got {status} [{license_id}] {detail}"
            )
    for invalid in INVALID_APPROVALS:
        try:
            parse_approvals(invalid, "self-test")
        except SystemExit:
            continue
        failures.append(f"  invalid approvals accepted: {invalid!r}")
    for expression, rust, expected in SELF_TEST_CASES:
        component = {"name": "probe", "version": "0.0.0"}
        if expression:
            component["licenses"] = [{"expression": expression}]
        status, license_id, detail = evaluate_component(
            component, rust, set(DEFAULT_DYNAMIC)
        )
        if status != expected:
            failures.append(
                f"  {expression!r} (rust={rust}): expected {expected}, got "
                f"{status} [{license_id}] {detail}"
            )
    # A component with no licence metadata at all must fail, not pass silently.
    status, _, _ = evaluate_component(
        {"name": "probe", "version": "0.0.0"}, {}, True, set()
    )
    if status != "fail":
        failures.append(f"  missing licence metadata: expected fail, got {status}")

    # Case folding is asserted on the CLASSIFICATION, not only on pass/fail.
    # A case-sensitive compare does not merely mis-sort a lower-case blocked
    # identifier -- it fails to recognise it at all, so the expression falls
    # through to "unknown", which also rejects the component. Both outcomes
    # read as "fail", so an ok/fail assertion cannot tell a blocked licence
    # from an unrecognised one, and the regression that let `gpl-3.0` past the
    # blocked list would sail through this suite. Pin the rank instead.
    blocked_casings = (
        "GPL-3.0", "gpl-3.0", "GpL-3.0",
        "GPL-2.0-only", "gpl-2.0-only",
        "GPL-3.0-or-later", "gpl-2.0-or-later",
        "AGPL-3.0", "agpl-3.0",
        "SSPL-1.0", "sspl-1.0",
        "GPL-2.0-only WITH Classpath-exception-2.0",
    )
    for identifier in blocked_casings:
        rank, _name = evaluate_expression(identifier)
        if rank != RANK_BLOCKED:
            failures.append(
                f"  {identifier!r}: expected RANK_BLOCKED ({RANK_BLOCKED}), "
                f"got rank {rank} -- case folding is not reaching the "
                f"blocked list"
            )

    # The review list needs the same treatment, and for the same reason the
    # ok/fail cases cannot cover it: LGPL is rejected for a Rust project
    # whether it classifies as RANK_REVIEW or falls through to RANK_UNKNOWN,
    # so only the rank distinguishes "review list matched" from "identifier
    # not recognised".
    review_casings = (
        "LGPL-2.1", "lgpl-2.1", "LgPl-2.1",
        "LGPL-3.0", "lgpl-3.0",
        "LGPL-2.1-or-later", "lgpl-3.0-or-later",
        "GPL-3.0-or-later WITH GCC-exception-3.1",
        "GPL-3.0-only WITH GCC-exception-3.1",
        "gpl-2.0-or-later with gcc-exception-2.0",
        # SPDX's deprecated identifier for the same grant.
        "GPL-3.0-with-GCC-exception",
    )
    for identifier in review_casings:
        rank, _name = evaluate_expression(identifier)
        if rank != RANK_REVIEW:
            failures.append(
                f"  {identifier!r}: expected RANK_REVIEW ({RANK_REVIEW}), "
                f"got rank {rank} -- case folding is not reaching the "
                f"review list"
            )

    # A reviewed licence document is read as the licences of its parts, each
    # still judged against the allowed list. Whitespace does not matter; any
    # other change to the text is a new document that needs its own review.
    document = "Combined LICENSE\n\nPart one, MIT.\n----\nPart two, BSD-3-Clause.\n"
    documents = {licence_document_digest(document): {
        "document": "probe", "expression": "MIT AND BSD-3-Clause",
        "approved-by": "Approver Name", "date": "2026-11-04"}}
    document_cases = [
        (document, "MIT AND BSD-3-Clause"),
        ("  Combined   LICENSE\nPart one, MIT.\n----\n\nPart two, BSD-3-Clause.", "MIT AND BSD-3-Clause"),
        (document.replace("BSD-3-Clause", "GPL-3.0"), None),
    ]
    for text, expected in document_cases:
        got = declared_license(_declared(text)["license"], documents)
        if got != expected:
            failures.append(f"  declared document {text[:30]!r}: expected {expected!r}, got {got!r}")
    for digest, entry in KNOWN_LICENCE_DOCUMENTS.items():
        missing = [f for f in ("document", "expression", "approved-by", "date") if not entry.get(f)]
        if missing or not re.fullmatch(r"[0-9a-f]{64}", digest):
            failures.append(f"  KNOWN_LICENCE_DOCUMENTS {digest[:12]}: missing {missing} or bad digest")

    # A library a package bundles, as detect_licenses.py records one it found
    # installed as a separate shared library. LGPL and GPL with a GCC runtime
    # exception pass there because the library is loaded dynamically, and
    # nowhere else.
    for expression, linkage, rust, expected in BUNDLED_CASES:
        bundled = {"name": "libquadmath", "licenses": [{"expression": expression}]}
        if linkage:
            bundled["properties"] = [{"name": LINKAGE_PROPERTY, "value": linkage}]
        parent = {"name": "numpy", "version": "1.26.4",
                  "licenses": [{"expression": "BSD-3-Clause"}], "components": [bundled]}
        walked = [c.get("name") for c in iter_components({"components": [parent]})]
        if walked != ["numpy", "libquadmath"]:
            failures.append(f"  bundled library not checked: components walked {walked}")
        status, license_id, detail = evaluate_component(bundled, rust, set(DEFAULT_DYNAMIC))
        if status != expected:
            failures.append(
                f"  bundled {expression!r} linkage={linkage} (rust={rust}): expected "
                f"{expected}, got {status} [{license_id}] {detail}"
            )

    if failures:
        print("license policy self-test FAILED:")
        print("\n".join(failures))
        return 1
    total = (
        len(COMPONENT_CASES) + len(APPROVAL_CASES) + len(INVALID_APPROVALS)
        + len(SELF_TEST_CASES) + 1
        + len(blocked_casings) + len(review_casings) + len(BUNDLED_CASES)
    )
    print(f"license policy self-test passed ({total} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Check the SPDX expression evaluator against known cases and exit",
    )
    parser.add_argument("sbom", nargs="?", help="CycloneDX JSON SBOM path")
    parser.add_argument(
        "--approvals",
        default=os.environ.get("LICENSE_APPROVALS_FILE"),
        help=f"Proprietary component approvals (default: {APPROVALS_FILE} if present)",
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if not args.sbom:
        parser.error("sbom path is required unless --self-test is given")

    with open(args.sbom, encoding="utf-8") as handle:
        sbom = json.load(handle)

    rust = is_rust_project()
    dynamic = dynamic_libraries()
    approvals = load_approvals(args.approvals)

    failures: List[str] = []
    warnings: List[str] = []
    ok_count = 0
    for component in iter_components(sbom):
        status, _license, detail = evaluate_component(
            component, rust, dynamic, approvals
        )
        if status == "ok":
            ok_count += 1
        elif status == "warn":
            warnings.append(detail)
        else:
            failures.append(detail)

    for warning in warnings:
        print(f"WARNING: {warning}")
    if failures:
        print("LICENSE VIOLATIONS DETECTED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"All licenses approved ({ok_count} components, {len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
