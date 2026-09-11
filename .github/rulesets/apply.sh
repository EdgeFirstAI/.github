# Apply org rulesets stored in this directory.
#
# Requires: gh auth refresh -h github.com -s admin:org
#
# Target list in protect-main*.json starts as .github + ci-foundation-scratch.
# Add product repositories as they grow a ci-gate job. Do not apply ci-gate
# to the whole org until those repos have the check.
# protect-release-tags stays ~ALL so v* tags cannot be created by hand in any
# repo. That is independent of the ci-gate rollout.
#
# protect-main: reviews. Org admins may merge their own PRs without a human
# approval (Copilot review is enough for them). Everyone else still needs a
# review. protect-main-ci: ci-gate, no force-push, no deletion; no bypass.
# protect-release-tags: block create/move/delete of v* tags. GitHub's built-in
# Actions app (15368) cannot be a bypass actor at org level; tag-release must
# use RELEASE_TAG_TOKEN owned by an OrganizationAdmin.

set -euo pipefail
ORG="${ORG:-EdgeFirstAI}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

for spec in protect-main.json protect-main-ci.json protect-release-tags.json; do
  name="$(jq -r .name "$ROOT/$spec")"
  existing="$(gh api "orgs/${ORG}/rulesets" --jq ".[] | select(.name==\"${name}\") | .id" || true)"
  if [[ -n "$existing" ]]; then
    echo "updating ruleset $name ($existing)"
    gh api --method PUT "orgs/${ORG}/rulesets/${existing}" --input "$ROOT/$spec"
  else
    echo "creating ruleset $name"
    gh api --method POST "orgs/${ORG}/rulesets" --input "$ROOT/$spec"
  fi
done
