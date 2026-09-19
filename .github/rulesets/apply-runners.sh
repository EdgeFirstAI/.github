#!/usr/bin/env bash
# Converge the organisation's runner groups, access lists and custom labels
# onto .github/rulesets/runners.json.
#
# Idempotent: a second run is a no-op. --dry-run prints what would change
# and touches nothing.
#
# .labels is authoritative per runner: a named runner's custom labels are
# made to match its declared list exactly, adding what is missing and
# removing what is not declared. A runner absent from .labels is
# unmanaged -- this script does not touch its labels at all -- exactly as
# a group absent from .groups is unmanaged; see the top-level "unmanaged"
# key in runners.json for what those are and why. Only Phase A can delete
# state; groups and membership remain additive/full-replacement.
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
# Removals get their own verb and line shape so a reader skimming --dry-run
# output can never mistake one for an addition.
run_remove() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "    would remove: $*"
  else
    "$@"
  fi
}

# Phase A -- custom labels, authoritative. Adds what a runner's declared
# list is missing and removes custom labels it has that are not declared.
say "Phase A: custom labels"
labels_spec="$(jq -r '.labels | to_entries[] | "\(.key)\t\(.value | join(","))"' "$SPEC")"
while IFS=$'\t' read -r name labels; do
  # A here-string built from an empty capture still yields one blank line,
  # so an empty .labels map would otherwise reach the id lookup with no name.
  [[ -z "$name" ]] && continue
  if [[ -z "$labels" ]]; then
    echo "::error::runner '$name' declares an empty label list in $SPEC -- refusing, since applying it would strip every custom label the runner has. Remove the runner from .labels instead if its labels are meant to be unmanaged." >&2
    exit 1
  fi
  id="$(gh api "orgs/$ORG/actions/runners" --paginate \
        --jq ".runners[] | select(.name==\"$name\") | .id")"
  if [[ -z "$id" ]]; then
    echo "::error::runner '$name' not found in $ORG" >&2
    exit 1
  fi
  # GitHub's auto-assigned labels (self-hosted, Linux, X64, ARM64, Windows,
  # macOS) are type: read-only and the API rejects removing them -- but that
  # is not relied on here. Filtering on type explicitly keeps the invariant
  # local rather than delegated to a remote error.
  have_custom="$(gh api "orgs/$ORG/actions/runners/$id" \
                 --jq '[.labels[] | select(.type=="custom") | .name]')"
  desired="$(printf '%s\n' ${labels//,/ } | jq -R . | jq -s .)"

  for label in ${labels//,/ }; do
    if jq -e --arg l "$label" 'index($l) != null' <<< "$have_custom" >/dev/null; then
      echo "    ok: $name already has $label"
      continue
    fi
    say "adding label '$label' to $name ($id)"
    run gh api --method POST "orgs/$ORG/actions/runners/$id/labels" \
      -f "labels[]=$label"
  done

  for label in $(jq -r '.[]' <<< "$have_custom"); do
    if jq -e --arg l "$label" 'index($l) != null' <<< "$desired" >/dev/null; then
      continue
    fi
    say "REMOVING label '$label' from $name ($id) -- not declared in runners.json"
    run_remove gh api --method DELETE \
      "orgs/$ORG/actions/runners/$id/labels/$label"
  done
done <<< "$labels_spec"

# Phase B -- access lists, before membership. Moving a runner into a
# visibility=selected group with an empty list makes it reachable by nothing.
say "Phase B: repository access lists"
groups_repos="$(jq -r '.groups | to_entries[] | "\(.key)\t\(.value.id)\t\(.value.repositories | join(","))"' "$SPEC")"
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
done <<< "$groups_repos"

# Phase C -- membership.
say "Phase C: group membership"
groups_runners="$(jq -r '.groups | to_entries[] | "\(.key)\t\(.value.id)\t\(.value.runners | join(","))"' "$SPEC")"
while IFS=$'\t' read -r group gid runners; do
  [[ -z "$runners" ]] && continue
  for name in ${runners//,/ }; do
    id="$(gh api "orgs/$ORG/actions/runners" --paginate \
          --jq ".runners[] | select(.name==\"$name\") | .id")"
    if [[ -z "$id" ]]; then
      echo "::error::runner '$name' not found in $ORG" >&2
      exit 1
    fi
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
done <<< "$groups_runners"

say "done"
