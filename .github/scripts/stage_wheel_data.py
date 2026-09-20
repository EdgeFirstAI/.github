#!/usr/bin/env python3
"""Place files into a built wheel's `.data/` directory.

maturin honours a `<module>.data/` directory staged before the build, but only
for a binding that produces a Python module. A `bindings = "bin"` wheel has no
such directory, so the only mechanism that serves both is to unpack the
finished wheel, add the files and pack it again -- which also removes the
caller's need to know which case it is in.

`wheel pack` recomputes `RECORD`, so the repacked wheel is a *different*
artifact with a different digest. That is why this runs before the attestation
step rather than after it: provenance generated for the pre-injection wheel
would describe something nobody can install.

Entries are `{from, scheme, path, mode, wheel}`:

    from    glob, relative to the working directory, of files to place
    scheme  wheel data scheme -- scripts, data, purelib, platlib, headers
    path    optional subdirectory under the scheme
    mode    optional octal chmod, applied before packing
    wheel   optional glob selecting which wheels this entry applies to

`mode` is not cosmetic. The Actions artifact store does not preserve the
executable bit, so a console script staged from a sibling job arrives 0644 and
the wheel fails at first use -- after publication, on a version PyPI will not
let you replace.

A `from` that matches nothing is an error. A payload that silently did not
arrive is the failure this exists to make loud, and it is the same reasoning
`payloads` applies to an empty artifact.

`wheel` exists because one lane may build several distributions: `builds` is a
list, and hal ships five from a single job. Injecting into every wheel in the
directory would be silently wrong for all but one of them. The default is
every wheel, which is right for the one-distribution lane.

Usage: stage_wheel_data.py
Reads ENTRIES (JSON array) and WHEEL_DIR from the environment.
"""

import fnmatch
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMES = ("scripts", "data", "purelib", "platlib", "headers")


class StageError(Exception):
    """A malformed entry, or a source or wheel that does not resolve."""


def parse_entries(raw):
    """Validate the JSON array and return it as a list of normalised dicts."""
    text = (raw or "").strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StageError(f"wheel-data is not valid JSON: {exc}") from exc
    if not isinstance(loaded, list):
        raise StageError("wheel-data must be a JSON array of objects")

    entries = []
    for index, item in enumerate(loaded):
        where = f"wheel-data[{index}]"
        if not isinstance(item, dict):
            raise StageError(f"{where} is not an object")
        unknown = set(item) - {"from", "scheme", "path", "mode", "wheel"}
        if unknown:
            raise StageError(f"{where} has unknown key(s): {', '.join(sorted(unknown))}")

        source = item.get("from")
        if not source or not isinstance(source, str):
            raise StageError(f"{where} needs a non-empty 'from' glob")

        scheme = item.get("scheme")
        if scheme not in SCHEMES:
            raise StageError(
                f"{where} has scheme {scheme!r}; expected one of {', '.join(SCHEMES)}"
            )

        subpath = item.get("path") or ""
        if subpath.startswith("/") or ".." in Path(subpath).parts:
            raise StageError(f"{where} path {subpath!r} must stay inside the scheme")

        mode = item.get("mode")
        if mode is not None:
            try:
                mode = int(str(mode), 8)
            except ValueError as exc:
                raise StageError(f"{where} mode {item['mode']!r} is not octal") from exc

        entries.append(
            {
                "from": source,
                "scheme": scheme,
                "path": subpath,
                "mode": mode,
                "wheel": item.get("wheel") or "*",
            }
        )
    return entries


def resolve_sources(entry, root):
    """Expand an entry's `from` glob. An empty match is an error, not a skip."""
    matches = sorted(
        path for path in glob.glob(entry["from"], root_dir=str(root), recursive=True)
        if (Path(root) / path).is_file()
    )
    if not matches:
        raise StageError(
            f"wheel-data 'from' glob {entry['from']!r} matched no files -- "
            "did the payload arrive?"
        )
    return [Path(root) / match for match in matches]


def find_wheels(wheel_dir):
    """Every wheel in the output directory. An sdist is not one."""
    return sorted(Path(wheel_dir).glob("*.whl"))


def plan(entries, wheels, root):
    """Group the work by wheel, so each is unpacked and packed exactly once.

    Returns {wheel_path: [(source, destination-relative-to-unpacked, mode)]}.
    An entry whose `wheel` glob selects nothing is an error: it names a
    distribution this lane did not build, which is a typo rather than a
    preference.
    """
    work = {wheel: [] for wheel in wheels}
    for index, entry in enumerate(entries):
        selected = [w for w in wheels if fnmatch.fnmatch(w.name, entry["wheel"])]
        if not selected:
            raise StageError(
                f"wheel-data[{index}] wheel glob {entry['wheel']!r} matched none of: "
                + ", ".join(w.name for w in wheels)
            )
        sources = resolve_sources(entry, root)
        for wheel in selected:
            for source in sources:
                destination = Path(entry["scheme"]) / entry["path"] / source.name
                work[wheel].append((source, destination, entry["mode"]))
    return {wheel: items for wheel, items in work.items() if items}


def _unpacked_root(parent, wheel):
    """The single directory `wheel unpack` produced, and its `.data/` sibling."""
    directories = [path for path in Path(parent).iterdir() if path.is_dir()]
    if len(directories) != 1:
        raise StageError(
            f"unpacking {wheel.name} produced {len(directories)} directories, expected 1"
        )
    return directories[0]


def apply_to_wheel(wheel, items, wheel_dir):
    """Unpack, place every file, pack. `wheel pack` recomputes RECORD."""
    with tempfile.TemporaryDirectory() as workdir:
        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", "-d", workdir, str(wheel)],
            check=True,
        )
        unpacked = _unpacked_root(workdir, wheel)
        data_dir = unpacked / f"{unpacked.name}.data"

        for source, destination, mode in items:
            target = data_dir / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if mode is not None:
                target.chmod(mode)
            print(f"  {source} -> {target.relative_to(unpacked)}")

        wheel.unlink()
        subprocess.run(
            [sys.executable, "-m", "wheel", "pack", "-d", str(wheel_dir), str(unpacked)],
            check=True,
        )


def main():
    root = Path.cwd()
    wheel_dir = Path(os.environ.get("WHEEL_DIR") or "target/wheels")
    try:
        entries = parse_entries(os.environ.get("ENTRIES"))
        if not entries:
            print("wheel-data: nothing to place")
            return 0
        wheels = find_wheels(wheel_dir)
        if not wheels:
            raise StageError(f"no wheels in {wheel_dir} to place files into")
        work = plan(entries, wheels, root)
    except StageError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    for wheel, items in work.items():
        print(f"::group::wheel-data {wheel.name}")
        apply_to_wheel(wheel, items, wheel_dir)
        print("::endgroup::")
    return 0


def _self_test() -> int:
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    def check_raises(label, fn):
        try:
            fn()
        except StageError:
            return
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: raised {type(exc).__name__}, want StageError")
            return
        failures.append(f"{label}: did not raise")

    # Empty input is not an error; it is the default.
    check("empty", parse_entries(""), [])
    check("empty array", parse_entries("[]"), [])

    check(
        "client's entry",
        parse_entries('[{"from": "payload/*/edgefirst-client*", '
                      '"scheme": "scripts", "mode": "0755"}]'),
        [{"from": "payload/*/edgefirst-client*", "scheme": "scripts",
          "path": "", "mode": 0o755, "wheel": "*"}],
    )
    check(
        "profiler's entry",
        parse_entries('[{"from": "payload/*/*.so", "scheme": "data", "path": "lib"}]'),
        [{"from": "payload/*/*.so", "scheme": "data",
          "path": "lib", "mode": None, "wheel": "*"}],
    )

    check_raises("bad JSON", lambda: parse_entries("[{"))
    check_raises("not an array", lambda: parse_entries('{"from": "x", "scheme": "data"}'))
    check_raises("not an object", lambda: parse_entries('["x"]'))
    check_raises("no from", lambda: parse_entries('[{"scheme": "data"}]'))
    check_raises("no scheme", lambda: parse_entries('[{"from": "x"}]'))
    check_raises("bad scheme", lambda: parse_entries('[{"from": "x", "scheme": "lib"}]'))
    check_raises("unknown key",
                 lambda: parse_entries('[{"from": "x", "scheme": "data", "to": "y"}]'))
    check_raises("bad mode",
                 lambda: parse_entries('[{"from": "x", "scheme": "data", "mode": "rwx"}]'))
    # A path that climbs out of the scheme would write anywhere in the wheel.
    check_raises("escaping path",
                 lambda: parse_entries('[{"from": "x", "scheme": "data", "path": "../.."}]'))
    check_raises("absolute path",
                 lambda: parse_entries('[{"from": "x", "scheme": "data", "path": "/etc"}]'))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "payload" / "shims").mkdir(parents=True)
        (root / "payload" / "shims" / "libtrt.so").write_text("x")
        (root / "payload" / "shims" / "libhailo.so").write_text("x")
        (root / "wheels").mkdir()
        one = root / "wheels" / "edgefirst_profiler-1.2.3-cp311-abi3-linux_aarch64.whl"
        two = root / "wheels" / "edgefirst_hal-1.2.3-cp311-abi3-linux_aarch64.whl"
        one.write_text("")
        two.write_text("")
        (root / "wheels" / "edgefirst_profiler-1.2.3.tar.gz").write_text("")

        check("sdist ignored", [w.name for w in find_wheels(root / "wheels")],
              [two.name, one.name])

        entry = parse_entries('[{"from": "payload/*/*.so", "scheme": "data", '
                              '"path": "lib"}]')
        # Both wheels by default, two sources each.
        work = plan(entry, find_wheels(root / "wheels"), root)
        check("default targets every wheel", len(work), 2)
        check("both sources placed", len(work[one]), 2)
        check(
            "destination under the scheme",
            sorted(str(dest) for _, dest, _ in work[one]),
            ["data/lib/libhailo.so", "data/lib/libtrt.so"],
        )

        scoped = parse_entries('[{"from": "payload/*/*.so", "scheme": "data", '
                               '"path": "lib", "wheel": "edgefirst_profiler-*"}]')
        work = plan(scoped, find_wheels(root / "wheels"), root)
        check("wheel glob scopes the entry", [w.name for w in work], [one.name])

        # A glob matching nothing is the payload-did-not-arrive case.
        missing = parse_entries('[{"from": "payload/*/*.dylib", "scheme": "data"}]')
        check_raises("from matched nothing",
                     lambda: plan(missing, find_wheels(root / "wheels"), root))

        # A wheel glob naming a distribution this lane did not build is a typo.
        wrong = parse_entries('[{"from": "payload/*/*.so", "scheme": "data", '
                              '"wheel": "edgefirst_client-*"}]')
        check_raises("wheel matched nothing",
                     lambda: plan(wrong, find_wheels(root / "wheels"), root))

        # A directory matching the glob is not a file to place.
        (root / "payload" / "shims" / "nested.so").mkdir()
        check("directories are not sources",
              len(resolve_sources(entry[0], root)), 2)

    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    print(f"stage_wheel_data self-test: {len(failures)} failure(s)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
