#!/usr/bin/env bash
# Converge the organisation's runner groups, access lists and custom labels
# onto .github/rulesets/runners.json.
#
# Idempotent: every operation is additive or a full replacement, so a second
# run is a no-op. --dry-run prints what would change and touches nothing.
#
# Requires: gh with admin:org (gh auth refresh -h github.com -s admin:org)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC="$HERE/runners.json"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

ORG="$(jq -r .org "$SPEC")"

say() { echo "==> $*"; }
run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "    would: $*"
  else
    "$@"
  fi
}

# Phase A -- labels. Purely additive; POST never removes a label.
say "Phase A: custom labels"
while IFS=$'\t' read -r name labels; do
  id="$(gh api "orgs/$ORG/actions/runners" --paginate \
        --jq ".runners[] | select(.name==\"$name\") | .id")"
  if [[ -z "$id" ]]; then
    echo "::error::runner '$name' not found in $ORG" >&2
    exit 1
  fi
  have="$(gh api "orgs/$ORG/actions/runners/$id" --jq '[.labels[].name] | join(",")')"
  for label in ${labels//,/ }; do
    if [[ ",$have," == *",$label,"* ]]; then
      echo "    ok: $name already has $label"
      continue
    fi
    say "adding label '$label' to $name ($id)"
    run gh api --method POST "orgs/$ORG/actions/runners/$id/labels" \
      -f "labels[]=$label"
  done
done < <(jq -r '.labels | to_entries[] | "\(.key)\t\(.value | join(","))"' "$SPEC")

# Phase B -- access lists, before membership. Moving a runner into a
# visibility=selected group with an empty list makes it reachable by nothing.
say "Phase B: repository access lists"
while IFS=$'\t' read -r group gid repos; do
  [[ -z "$repos" ]] && { echo "    skip: $group keeps an empty access list"; continue; }
  ids=()
  for repo in ${repos//,/ }; do
    ids+=("$(gh api "repos/$ORG/$repo" --jq .id)")
  done
  desired="$(printf '%s\n' "${ids[@]}" | jq -R 'tonumber' | jq -sc 'sort')"
  current="$(gh api "orgs/$ORG/actions/runner-groups/$gid/repositories" \
             --jq '[.repositories[].id] | sort' | jq -c .)"
  if [[ "$desired" == "$current" ]]; then
    echo "    ok: $group access list already correct"
    continue
  fi
  payload="$(printf '%s\n' "${ids[@]}" | jq -R 'tonumber' | jq -s '{selected_repository_ids: .}')"
  say "setting $group ($gid) access to: $repos"
  if [[ "$DRY_RUN" == true ]]; then
    echo "    would: PUT runner-groups/$gid/repositories <- $payload"
  else
    echo "$payload" | gh api --method PUT \
      "orgs/$ORG/actions/runner-groups/$gid/repositories" --input -
  fi
done < <(jq -r '.groups | to_entries[] | "\(.key)\t\(.value.id)\t\(.value.repositories | join(","))"' "$SPEC")

# Phase C -- membership.
say "Phase C: group membership"
while IFS=$'\t' read -r group gid runners; do
  [[ -z "$runners" ]] && continue
  for name in ${runners//,/ }; do
    id="$(gh api "orgs/$ORG/actions/runners" --paginate \
          --jq ".runners[] | select(.name==\"$name\") | .id")"
    # `gh --jq` prints an empty string for a null result rather than the text
    # "null", so comparing against "null" treats an absent runner as present.
    # Coercing to a boolean keeps the output unambiguous.
    in_group="$(gh api "orgs/$ORG/actions/runner-groups/$gid/runners" \
                --jq "[.runners[].name] | index(\"$name\") != null")"
    if [[ "$in_group" == "true" ]]; then
      echo "    ok: $name already in $group"
      continue
    fi
    say "moving $name ($id) into $group ($gid)"
    run gh api --method PUT "orgs/$ORG/actions/runner-groups/$gid/runners/$id"
  done
done < <(jq -r '.groups | to_entries[] | "\(.key)\t\(.value.id)\t\(.value.runners | join(","))"' "$SPEC")

say "done"
