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
    "ISC AND MIT",
    "MIT AND Apache-2.0",
    "Apache-2.0 OR MIT",
    "MIT OR Apache-2.0",
    "BSD-3-Clause OR MIT",
}

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

    for license_id in licenses:
        if license_id in BLOCKED_LICENSES or license_id.startswith("GPL") or license_id.startswith("AGPL"):
            return "fail", license_id, f"{key}: blocked license {license_id}"
        if license_id in REVIEW_REQUIRED_LICENSES or license_id.startswith("LGPL"):
            if rust:
                return "fail", license_id, (
                    f"{key}: LGPL ({license_id}) is forbidden in Rust "
                    "(static linking cannot satisfy LGPL)"
                )
            if name.split("-")[0] not in dynamic and name not in dynamic:
                return "fail", license_id, (
                    f"{key}: LGPL ({license_id}) allowed only for documented "
                    "dynamically linked libraries"
                )
            return "warn", license_id, f"{key}: LGPL permitted as dynamic {license_id}"
        if license_id in CONDITIONAL_PROPRIETARY_LICENSES or "proprietary" in license_id.lower():
            return "warn", license_id, (
                f"{key}: proprietary {license_id} must be documented in NOTICE"
            )
        if license_id in ALLOWED_LICENSES:
            continue
        if " OR " in license_id:
            options = {part.strip() for part in license_id.split(" OR ")}
            if options & ALLOWED_LICENSES:
                continue
        if " AND " in license_id:
            parts = {part.strip() for part in license_id.split(" AND ")}
            if parts <= ALLOWED_LICENSES:
                continue
        return "fail", license_id, f"{key}: license {license_id} is not on the allowed list"
    return "ok", licenses[0], f"{key}: {licenses[0]}"


def iter_components(sbom: dict) -> Iterable[dict]:
    for component in sbom.get("components") or []:
        yield component
    metadata = sbom.get("metadata") or {}
    component = metadata.get("component")
    if component:
        for nested in component.get("components") or []:
            yield nested


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbom", help="CycloneDX JSON SBOM path")
    parser.add_argument(
        "--overrides",
        default=os.environ.get("LICENSE_OVERRIDES_FILE"),
        help="JSON object of name@version -> SPDX id",
    )
    args = parser.parse_args()

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
