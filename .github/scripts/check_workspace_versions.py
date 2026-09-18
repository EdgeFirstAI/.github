#!/usr/bin/env python3
"""Check a workspace's internal crate versions against the release version.

A workspace that versions its members through `[workspace.dependencies]`
carries the release version once per member on top of `[workspace.package]`.
Bumping only the latter passes every other check and still ships a wrong
dependency graph: each member then depends on the *previous* release of its
sibling, a version that exists on the registry, so `cargo publish` accepts it
without complaint. `cargo package` does not catch it either, because it
resolves the path dependency locally.

Cargo accepts both the inline form and the table form, and a regex over lines
sees only the first:

    [workspace.dependencies]
    foo = { version = "1.2.0", path = "crates/foo" }

    [workspace.dependencies.bar]
    version = "1.2.0"
    path = "crates/bar"

so the manifest is parsed rather than scanned. Only entries carrying BOTH
`path` and `version` are checked: those are this workspace's own crates as
they will be published. A third-party entry has no `path` and is left alone.

Usage: check_workspace_versions.py <version> [manifest]
Exit 0 when every internal version is the release version or its base form.
"""

import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    print("::error::python3.11+ with tomllib is required for the manifest check")
    sys.exit(1)


def main() -> int:
    if not 2 <= len(sys.argv) <= 3:
        print(__doc__)
        return 2
    version = sys.argv[1]
    manifest = sys.argv[2] if len(sys.argv) > 2 else "Cargo.toml"
    base = version.split("-rc")[0]

    try:
        with open(manifest, "rb") as fh:
            doc = tomllib.load(fh)
    except FileNotFoundError:
        print(f"no {manifest}; nothing to check")
        return 0
    except tomllib.TOMLDecodeError as exc:
        print(f"::error file={manifest}::not valid TOML: {exc}")
        return 1

    deps = doc.get("workspace", {}).get("dependencies", {})
    if not deps:
        print("no [workspace.dependencies]; nothing to check")
        return 0

    fail = 0
    checked = 0
    for name, spec in sorted(deps.items()):
        # A bare `foo = "1.2"` is a third-party dependency by definition: it
        # has no path, so it is not a member of this workspace.
        if not isinstance(spec, dict):
            continue
        if "path" not in spec or "version" not in spec:
            continue
        found = str(spec["version"]).lstrip("=^~").strip()
        checked += 1
        where = f"{manifest} [workspace.dependencies.{name}]"
        if found in (version, base):
            print(f"ok  {where}  {found}")
        else:
            print(
                f"::error file={manifest}::{where} version '{found}' is neither "
                f"'{version}' nor '{base}'. Bumping [workspace.package] alone "
                f"leaves {name} depending on its previous release, which the "
                f"registry accepts."
            )
            fail = 1

    if checked == 0:
        print("no internal path+version dependencies; nothing to check")
    return fail


if __name__ == "__main__":
    sys.exit(main())
