#!/usr/bin/env python3
"""Check CycloneDX SBOM license policy (Au-Zone SPS).

Policy version: 2.0 (2025-11-24). This is the single org-wide copy.

Exit 0 when every component is allowed or an approved override.
Exit 1 on blocked licenses, LGPL in Rust, or undocumented proprietary.
"""

from __future__ import annotations

import argparse
import json
import os
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

# Known-bad or missing metadata. Org-wide facts, not per-repo taste.
LICENSE_OVERRIDES: Dict[str, str] = {
    "sublime_fuzzy@0.7.0": "Apache-2.0",
    "dma-buf@0.4.0": "MIT",
    "dma-buf@0.5.0": "MIT",
    "dma-heap@0.4.1": "MIT",
}

DEFAULT_DYNAMIC: Set[str] = {"gstreamer", "glib", "libglib"}


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
    }
    return aliases.get(text, text)


def licenses_from_component(component: dict) -> List[str]:
    found: List[str] = []
    for entry in component.get("licenses") or []:
        license_obj = entry.get("license") or {}
        if "id" in license_obj:
            found.append(normalize_license(license_obj["id"]))
        elif "name" in license_obj:
            found.append(normalize_license(license_obj["name"]))
        elif "expression" in entry:
            found.append(normalize_license(entry["expression"]))
    return found


def component_key(component: dict) -> str:
    name = component.get("name") or "unknown"
    version = component.get("version") or ""
    return f"{name}@{version}" if version else name


def load_overrides(path: Optional[str]) -> Dict[str, str]:
    merged = dict(LICENSE_OVERRIDES)
    if not path:
        return merged
    with open(path, encoding="utf-8") as handle:
        extra = json.load(handle)
    if not isinstance(extra, dict):
        raise SystemExit(f"overrides file {path} must be a JSON object")
    merged.update({str(key): str(value) for key, value in extra.items()})
    return merged


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
        # Operators are case-insensitive in SPDX and bind only on word
        # boundaries, so "ORACLE" and "SAND" are never read as operators.
        for operator in ("AND", "OR", "WITH"):
            end = index + len(operator)
            if (
                expression[index:end].upper() == operator
                and (index == 0 or not expression[index - 1].isalnum())
                and (end >= len(expression) or not expression[end].isalnum())
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


def classify_leaf(leaf: str) -> Tuple[int, str]:
    license_id = _normalize_leaf(leaf)
    if not license_id:
        return RANK_UNKNOWN, "UNKNOWN"
    folded = license_id.lower()
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


def evaluate_component(
    component: dict,
    overrides: Dict[str, str],
    rust: bool,
    dynamic: Set[str],
) -> Tuple[str, str, str]:
    """Return (status, license, detail) status in {ok, warn, fail}."""
    key = component_key(component)
    name = (component.get("name") or "").lower()
    licenses = licenses_from_component(component)
    if key in overrides:
        licenses = [overrides[key]]
    if not licenses:
        return "fail", "UNKNOWN", f"{key}: missing license metadata"

    # Multiple license entries on one component are alternatives, so the best
    # outcome wins, matching OR. Seed from the first entry rather than a
    # constant, so the reported id is always the leaf that decided the verdict.
    best_rank, best_license = evaluate_expression(licenses[0])
    for expression in licenses[1:]:
        if best_rank == RANK_ALLOWED:
            break
        rank, license_id = evaluate_expression(expression)
        if rank < best_rank:
            best_rank, best_license = rank, license_id

    if best_rank == RANK_ALLOWED:
        return "ok", best_license, f"{key}: {best_license}"
    if best_rank == RANK_PROPRIETARY:
        return "warn", best_license, (
            f"{key}: proprietary {best_license} must be documented in NOTICE"
        )
    if best_rank == RANK_REVIEW:
        if rust:
            return "fail", best_license, (
                f"{key}: LGPL ({best_license}) is forbidden in Rust "
                "(static linking cannot satisfy LGPL)"
            )
        if name.split("-")[0] not in dynamic and name not in dynamic:
            return "fail", best_license, (
                f"{key}: LGPL ({best_license}) allowed only for documented "
                "dynamically linked libraries"
            )
        return "warn", best_license, f"{key}: LGPL permitted as dynamic {best_license}"
    if best_rank == RANK_BLOCKED:
        return "fail", best_license, f"{key}: blocked license {best_license}"
    return "fail", best_license, (
        f"{key}: license {best_license} is not on the allowed list"
    )


def iter_components(sbom: dict) -> Iterable[dict]:
    for component in sbom.get("components") or []:
        yield component
    metadata = sbom.get("metadata") or {}
    component = metadata.get("component")
    if component:
        for nested in component.get("components") or []:
            yield nested


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
]


def run_self_test() -> int:
    failures = []
    for expression, rust, expected in SELF_TEST_CASES:
        component = {"name": "probe", "version": "0.0.0"}
        if expression:
            component["licenses"] = [{"expression": expression}]
        status, license_id, detail = evaluate_component(
            component, dict(LICENSE_OVERRIDES), rust, set(DEFAULT_DYNAMIC)
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
        "AGPL-3.0", "agpl-3.0",
        "SSPL-1.0", "sspl-1.0",
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
    )
    for identifier in review_casings:
        rank, _name = evaluate_expression(identifier)
        if rank != RANK_REVIEW:
            failures.append(
                f"  {identifier!r}: expected RANK_REVIEW ({RANK_REVIEW}), "
                f"got rank {rank} -- case folding is not reaching the "
                f"review list"
            )

    if failures:
        print("license policy self-test FAILED:")
        print("\n".join(failures))
        return 1
    total = len(SELF_TEST_CASES) + 1 + len(blocked_casings) + len(review_casings)
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
        "--overrides",
        default=os.environ.get("LICENSE_OVERRIDES_FILE"),
        help="JSON object of name@version -> SPDX id",
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
    overrides = load_overrides(args.overrides)

    failures: List[str] = []
    warnings: List[str] = []
    ok_count = 0
    for component in iter_components(sbom):
        status, _license, detail = evaluate_component(component, overrides, rust, dynamic)
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
