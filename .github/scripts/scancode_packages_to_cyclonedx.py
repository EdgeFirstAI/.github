#!/usr/bin/env python3
"""Convert ScanCode native JSON packages to a CycloneDX 1.5 BOM.

ScanCode 32.4.1 ``--cyclonedx`` sets ``--full-root`` and then conflicts with
``--strip-root``, so Full SBOM writes ``--json-pp`` and maps packages here.
The mapping matches ``formattedcode.output_cyclonedx.CycloneDxComponent``:
``bom-ref`` is the PURL so ``merge_sboms`` can dedupe against cargo-cyclonedx.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional

HASH_ALGS = {
    "md5": "MD5",
    "sha1": "SHA-1",
    "sha256": "SHA-256",
    "sha512": "SHA-512",
}

URL_TYPES = {
    "api_data_url": "bom",
    "bug_tracking_url": "issue-tracker",
    "code_view_url": "other",
    "download_url": "distribution",
    "homepage_url": "website",
    "repository_download_url": "distribution",
    "repository_homepage_url": "website",
    "vcs_url": "vcs",
}


def author_from_parties(parties: Optional[Iterable[Mapping[str, Any]]]) -> Optional[str]:
    if not parties:
        return None
    names = [
        party.get("name")
        for party in parties
        if party.get("role") == "author" and party.get("name")
    ]
    return "\n".join(names) or None


def component_from_package(package: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a CycloneDX component, or None when name or version is missing."""
    name = package.get("name")
    version = package.get("version")
    if not (name and version):
        return None

    purl = package.get("purl")
    component: Dict[str, Any] = {
        "type": "library",
        "name": name,
        "version": version,
        "scope": "required",
    }
    if purl:
        component["bom-ref"] = purl
        component["purl"] = purl

    group = package.get("namespace")
    if group:
        component["group"] = group

    author = author_from_parties(package.get("parties"))
    if author:
        component["author"] = author

    copyright_text = package.get("copyright")
    if copyright_text:
        component["copyright"] = copyright_text

    description = package.get("description")
    if description:
        component["description"] = description

    hashes = [
        {"alg": cdx_alg, "content": digest}
        for field, cdx_alg in HASH_ALGS.items()
        if (digest := package.get(field))
    ]
    if hashes:
        component["hashes"] = hashes

    expression = (
        package.get("declared_license_expression_spdx")
        or package.get("declared_license_expression")
    )
    if expression:
        component["licenses"] = [{"expression": expression}]

    references = [
        {"type": ref_type, "url": url}
        for field, ref_type in URL_TYPES.items()
        if (url := package.get(field))
    ]
    if references:
        component["externalReferences"] = references

    return component


def components_from_packages(packages: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Unique components keyed by PURL, then (name, version). Later copies fill gaps."""
    by_key: Dict[Any, Dict[str, Any]] = {}
    for package in packages:
        component = component_from_package(package)
        if component is None:
            continue
        key = component.get("purl") or (component["name"], component["version"])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = component
            continue
        for field, value in component.items():
            if field not in existing or not existing[field]:
                existing[field] = value
    return list(by_key.values())


def bom_from_scan(data: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": components_from_packages(data.get("packages") or []),
    }


def merge_identity(component: Mapping[str, Any]) -> Any:
    """Identity used when merging cargo-cyclonedx and ScanCode components."""
    return (
        component.get("purl")
        or component.get("bom-ref")
        or (component.get("name"), component.get("version"))
    )


def _self_test() -> None:
    package = {
        "name": "serde",
        "version": "1.0.0",
        "namespace": "rust",
        "purl": "pkg:cargo/serde@1.0.0",
        "copyright": "Copyright 2015",
        "description": "Serde",
        "sha256": "ab" * 32,
        "parties": [{"role": "author", "name": "dtolnay"}],
        "declared_license_expression_spdx": "MIT OR Apache-2.0",
        "homepage_url": "https://serde.rs",
        "vcs_url": "https://github.com/serde-rs/serde",
    }
    component = component_from_package(package)
    assert component is not None
    assert component["bom-ref"] == package["purl"]
    assert component["purl"] == package["purl"]
    assert component["group"] == "rust"
    assert component["author"] == "dtolnay"
    assert component["copyright"] == "Copyright 2015"
    assert component["description"] == "Serde"
    assert component["hashes"] == [{"alg": "SHA-256", "content": "ab" * 32}]
    assert component["licenses"] == [{"expression": "MIT OR Apache-2.0"}]
    assert component["externalReferences"] == [
        {"type": "website", "url": "https://serde.rs"},
        {"type": "vcs", "url": "https://github.com/serde-rs/serde"},
    ]
    assert component_from_package({"purl": "pkg:cargo/x@1"}) is None

    cargo = {
        "name": "serde",
        "version": "1.0.0",
        "purl": "pkg:cargo/serde@1.0.0",
        "bom-ref": "pkg:cargo/serde@1.0.0",
        "licenses": [{"expression": "MIT OR Apache-2.0"}],
    }
    scancode = {
        "name": "serde",
        "version": "1.0.0",
        "purl": "pkg:cargo/serde@1.0.0",
        "copyright": "Copyright 2015",
    }
    assert merge_identity(cargo) == merge_identity(scancode)
    assert merge_identity(scancode) == merge_identity(
        {"name": "serde", "version": "1.0.0", "purl": "pkg:cargo/serde@1.0.0"}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scan_json",
        nargs="?",
        help="ScanCode --json-pp output",
    )
    parser.add_argument(
        "dest",
        nargs="?",
        help="CycloneDX JSON path to write",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("ok")
        return 0
    if not args.scan_json or not args.dest:
        parser.error("scan_json and dest are required unless --self-test")
    with open(args.scan_json, encoding="utf-8") as handle:
        data = json.load(handle)
    doc = bom_from_scan(data)
    with open(args.dest, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
