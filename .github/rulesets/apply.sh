# Apply org rulesets stored in this directory.
#
# Requires: gh auth refresh -h github.com -s admin:org
#
# protect-main*.json target the organisation custom property `ci_tier`, not a
# list of repository names: a repository is covered once it is set to `tiered`,
# which is a setting on that repository rather than an edit here. Onboard one
# with
#
#   gh api --method PATCH orgs/EdgeFirstAI/properties/values \
#     -f 'repository_names[]=<repo>' \
#     -f 'properties[][property_name]=ci_tier' -f 'properties[][value]=tiered'
#
# Set it only once the repository has a ci-gate check, or its main branch
# requires a check that can never report. Nothing enforces that ordering.
#
# A repository set to `tiered` must have its own hand-made protect-main and
# protect-release-tags rulesets deleted, or the two layers both apply and no
# single file is the source of truth. See the EDGEAI-1554 close-out.
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

# gh --jq is used throughout rather than a standalone jq binary, which is not
# present on a stock Git Bash and made this script unrunnable on Windows.
for spec in protect-main.json protect-main-ci.json protect-release-tags.json; do
  name="${spec%.json}"
  existing="$(gh api "orgs/${ORG}/rulesets" --jq ".[] | select(.name==\"${name}\") | .id" | head -1 || true)"
  if [[ -n "$existing" ]]; then
    echo "updating ruleset $name ($existing)"
    # Response body is discarded: gh api emits no trailing newline, which ran
    # the JSON into the next iteration's message. Errors still reach stderr.
    gh api --method PUT "orgs/${ORG}/rulesets/${existing}" --input "$ROOT/$spec" > /dev/null
  else
    echo "creating ruleset $name"
    gh api --method POST "orgs/${ORG}/rulesets" --input "$ROOT/$spec" > /dev/null
  fi
done
