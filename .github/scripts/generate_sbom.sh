#!/usr/bin/env bash
# Generate a CycloneDX SBOM and enforce the Au-Zone license policy.
#
# This is the single org-wide copy. Callers pass project identity through
# environment variables; do not fork the script per repository.
#
# Required:
#   PROJECT_NAME          crate / package / application name
# Optional:
#   PROJECT_TYPE          library | application | framework (default: library)
#   VERSION_FILE          file to read version from (default: Cargo.toml)
#   SOURCE_DIRS           directories for scancode (default: src tests)
#   MANIFEST_FILES        unused except documentation
#   SBOM_MODE             dependency | full (default: dependency)
#   OUTPUT_DIR            default: sbom
#   NOTICE_FILE           default: NOTICE
#   SCRIPT_DIR            directory containing the sibling Python policy scripts
#
# Policy version: 2.0 (2025-11-24)

set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:?PROJECT_NAME is required}"
PROJECT_TYPE="${PROJECT_TYPE:-library}"
VERSION_FILE="${VERSION_FILE:-Cargo.toml}"
SOURCE_DIRS="${SOURCE_DIRS:-src tests}"
SBOM_MODE="${SBOM_MODE:-dependency}"
OUTPUT_DIR="${OUTPUT_DIR:-sbom}"
NOTICE_FILE="${NOTICE_FILE:-NOTICE}"
SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

mkdir -p "$OUTPUT_DIR"

version_from_file() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "unknown"
    return
  fi
  case "$file" in
    Cargo.toml|*/Cargo.toml)
      grep -E '^version\s*=' "$file" | head -1 | sed 's/.*"\(.*\)".*/\1/'
      ;;
    pyproject.toml|*/pyproject.toml)
      grep -E '^version\s*=' "$file" | head -1 | sed 's/.*"\(.*\)".*/\1/'
      ;;
    VERSION|version)
      tr -d '[:space:]' < "$file"
      ;;
    *)
      grep -E 'version' "$file" | head -1 | sed 's/.*"\([0-9][^"]*\)".*/\1/'
      ;;
  esac
}

VERSION="$(version_from_file "$VERSION_FILE")"
echo "=================================================="
echo "SBOM for ${PROJECT_NAME} ${VERSION} (${PROJECT_TYPE}), mode=${SBOM_MODE}"
echo "=================================================="

DEP_SBOM="${OUTPUT_DIR}/sbom-dependencies.json"
SRC_SBOM="${OUTPUT_DIR}/sbom-source.json"
MERGED_SBOM="${OUTPUT_DIR}/sbom.json"

generate_dependency_sbom() {
  if [[ -f Cargo.toml ]]; then
    if ! cargo cyclonedx -h >/dev/null 2>&1; then
      echo "error: cargo-cyclonedx is required (install via taiki-e/install-action)" >&2
      exit 1
    fi
    cargo cyclonedx --format json --all
    python3 - "$DEP_SBOM" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
components = []
seen = set()
for path in pathlib.Path(".").rglob("*.cdx.json"):
    if ".ef-ci" in path.parts or "target" in path.parts:
        continue
    doc = json.loads(path.read_text(encoding="utf-8"))
    for component in doc.get("components") or []:
        key = (component.get("purl") or component.get("name"), component.get("version"))
        if key in seen:
            continue
        seen.add(key)
        components.append(component)
    meta = (doc.get("metadata") or {}).get("component")
    if meta:
        key = (meta.get("purl") or meta.get("name"), meta.get("version"))
        if key not in seen:
            seen.add(key)
            components.append(meta)
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as handle:
    json.dump({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": components}, handle, indent=2)
    handle.write("\n")
print(f"merged {len(components)} components into {out}")
PY
  elif [[ -f pyproject.toml ]]; then
    if command -v uv >/dev/null 2>&1; then
      uv run --with 'cyclonedx-bom==7.3.0' cyclonedx-py environment \
        --spec-version 1.5 --output-format JSON -o "$DEP_SBOM" --pyproject pyproject.toml
    elif command -v cyclonedx-py >/dev/null 2>&1; then
      env_path=()
      if [[ -d .venv ]]; then
        env_path=(.venv)
      fi
      cyclonedx-py environment --spec-version 1.5 --output-format JSON \
        -o "$DEP_SBOM" --pyproject pyproject.toml "${env_path[@]}"
    else
      echo "error: cyclonedx-py or uv is required when pyproject.toml exists" >&2
      exit 1
    fi
  else
    echo '{"bomFormat":"CycloneDX","specVersion":"1.5","components":[]}' > "$DEP_SBOM"
  fi
}

generate_source_sbom() {
  local scancode_bin=""
  if [[ -x venv/bin/scancode ]]; then
    scancode_bin=venv/bin/scancode
  elif command -v scancode >/dev/null 2>&1; then
    scancode_bin="$(command -v scancode)"
  else
    echo "error: scancode is required for SBOM_MODE=full" >&2
    exit 1
  fi

  local args=()
  # shellcheck disable=SC2206
  local dirs=( $SOURCE_DIRS )
  for dir in "${dirs[@]}"; do
    if [[ -d "$dir" ]]; then
      args+=("$dir")
    fi
  done
  if [[ ${#args[@]} -eq 0 ]]; then
    args=(.)
  fi

  "$scancode_bin" \
    --license --copyright --package \
    --cyclonedx "$SRC_SBOM" \
    --processes "${SCANCODE_PROCESSES:-4}" \
    "${args[@]}"
}

merge_sboms() {
  python3 - "$DEP_SBOM" "$SRC_SBOM" "$MERGED_SBOM" "$PROJECT_NAME" "$VERSION" "$PROJECT_TYPE" <<'PY'
import json, sys
dep_path, src_path, out_path, name, version, project_type = sys.argv[1:7]

def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"components": []}

dep = load(dep_path)
src = load(src_path)
components = []
seen = set()
for bom in (dep, src):
    for component in bom.get("components") or []:
        key = (component.get("name"), component.get("version"), component.get("bom-ref"))
        if key in seen:
            continue
        seen.add(key)
        components.append(component)

doc = {
    "bomFormat": "CycloneDX",
    "specVersion": dep.get("specVersion") or src.get("specVersion") or "1.5",
    "metadata": {
        "component": {"type": project_type, "name": name, "version": version},
    },
    "components": components,
}
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(doc, handle, indent=2)
    handle.write("\n")
PY
}

generate_dependency_sbom

if [[ "$SBOM_MODE" == "full" ]]; then
  generate_source_sbom
  merge_sboms
else
  if [[ -f "$DEP_SBOM" ]]; then
    cp "$DEP_SBOM" "$MERGED_SBOM"
  else
    echo '{"bomFormat":"CycloneDX","specVersion":"1.5","components":[]}' > "$MERGED_SBOM"
  fi
fi

if [[ ! -f "$MERGED_SBOM" ]]; then
  echo "error: failed to produce $MERGED_SBOM" >&2
  exit 1
fi

python3 - "$MERGED_SBOM" "$PROJECT_NAME" "$VERSION" "$PROJECT_TYPE" <<'PY'
import json, sys
path, name, version, project_type = sys.argv[1:5]
with open(path, encoding="utf-8") as handle:
    doc = json.load(handle)
metadata = doc.setdefault("metadata", {})
component = metadata.setdefault("component", {})
component["name"] = name
component["version"] = version
component["type"] = project_type
with open(path, "w", encoding="utf-8") as handle:
    json.dump(doc, handle, indent=2)
    handle.write("\n")
PY

python3 "$SCRIPT_DIR/check_license_policy.py" "$MERGED_SBOM"
python3 "$SCRIPT_DIR/validate_notice.py" "$MERGED_SBOM" --notice "$NOTICE_FILE"

echo "Wrote $MERGED_SBOM"
