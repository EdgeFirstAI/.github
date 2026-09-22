# Self-hosted runner groups

Organisation, not access control. Labels describe what a machine has and are what a workflow selects on; the group just gathers runners under a name. **No group is scoped to a repository list.** Every group is `visibility: all`, reachable by every repository in the organisation. Group settings live in [`runners.json`](runners.json) and are applied by [`apply_runners.py`](../scripts/apply_runners.py) — edit the JSON in a pull request rather than clicking through organisation settings, which is how the fleet drifted from this document in the first place.

This repository is `EdgeFirstAI/.github`, which is public. `runners.json` therefore names **groups only** — category configuration, not machines. It does not, and must not, list runner names, labels or which runner belongs to which group: that would make this public repository a de facto inventory of the internal board farm. The fleet's actual composition — which boards exist, what they're fitted with, which runner carries which label — is Confluence content (the "CICD Pipelines" space), not repository content.

A repository access list bounded which repositories could reach a runner, never which events could. It cannot distinguish a fork's pull request from the base repository's own push, because both run under the base repository's name.

Within the shared workflows, [`resolve_lanes.py`](../scripts/resolve_lanes.py) fails closed: `push`, `workflow_dispatch`, `schedule` and `merge_group` are trusted, a `pull_request` is trusted only when its head repository equals the base repository, and every other event degrades to a GitHub-hosted runner. **That guard binds only the jobs that call it.**

## What bounds a fork pull request

Not group scoping, and not `resolve_lanes.py`. On `pull_request` against a public repository GitHub runs the workflow as the fork's head defines it, so a job that names a self-hosted runner directly never passes through the shared workflows at all. Scoping did not gate this either — the repositories that consume these runners are themselves public — though it did bound how many repositories it applied to.

The governing control is the organisation's **fork pull-request approval policy**, which no workflow change can bypass. It must be set so that workflows from external contributors require maintainer approval before they run; `all_external_contributors` is that setting, and the weaker values leave returning contributors ungated. Confirm it with:

```bash
gh api orgs/EdgeFirstAI/actions/permissions/fork-pr-contributor-approval
```

Treat this as the boundary for self-hosted capacity. `resolve_lanes.py` hardens the shared workflows; it cannot constrain a workflow that declines to use them.

## Reconciled settings

`visibility` and `allows_public_repositories` are both declared per group and reconciled, and they travel in a single PATCH. A group narrowed to `selected` through the web UI is drift the converger catches. `allows_public_repositories` must stay `true` — the consuming repositories are themselves public, and that flag gates whether a public repository may use a group at all, so a group flipped to `false` strands every one of them while nothing else looks wrong.

This is the only state `runners.json` tracks. Unlike a runner's labels or group membership, a group's visibility can be changed by hand through the web UI with no local event to prompt anyone to notice, so it genuinely needs an ongoing, declarative converger. A runner's identity does not: see "Registering a runner" below.

## Applying

```bash
gh auth refresh -h github.com -s admin:org
python3 .github/scripts/apply_runners.py --dry-run   # review
python3 .github/scripts/apply_runners.py             # apply
```

## Registering a runner

**Register with no custom labels.** Do not pass `--labels` to `config.sh` — let the agent assert only its defaults (`self-hosted` plus OS and architecture). A label set there is reasserted by the agent on every reconnect, which fights any label applied afterwards through the API over casing or content. Every custom label is applied through the API instead, once, at provisioning time:

- **A board** gets its labels *derived* from its own registered name — family, identity and equipment, per the label convention below — by [`provision_runner.sh`](../scripts/provision_runner.sh). Group membership is set in the same step via `config.sh --runnergroup boards`. Nothing about a board's identity is stored in this repository: if a board is reflashed or re-registered, re-running its provisioning step reconstructs its labels from its name, the same way every time. The SSH host used to reach a board and the name it registers under are not required to match — see the script's usage comment.
- **A non-board runner** (a build box, a CUDA host, the Yocto builder) has labels that don't follow a derivable naming pattern, so they're applied by hand with a single `gh api` call when the machine is set up, the same as a board's used to be applied from `runners.json`. This is a one-time step, not an ongoing declarative spec: these machines are stable and don't drift the way a board that gets reflashed does.

## Label convention

Labels are generative, not a maintained list: a runner is described by four facts, and its label set follows from them mechanically. This is what lets provisioning derive labels instead of anyone maintaining a table.

- **family** — the processor family, e.g. an NXP i.MX or Rockchip part number, an NVIDIA Jetson line.
- **board** — the board within that family. Omitted when the family name is the whole board (some product lines have no separate board slot).
- **equipment** — zero or more fitted extras (an accelerator, a HAT, a carrier option).
- **bsp** — the pinned BSP version, when known.

| Label | Form |
| --- | --- |
| family | `<family>` |
| identity | `<family>-<board>` |
| pinned BSP | `<identity>-<bsp>` |
| equipment, bare | `<equipment>` |
| equipment, compound | `<identity>-<equipment>` |

Worked examples, using placeholders rather than any specific board:

- A `<family>-<board>` fitted with `<equipment>` generates `<family>`, `<family>-<board>`, `<equipment>` and `<family>-<board>-<equipment>`, plus a pinned-BSP label once the BSP is known.
- A `<family>` whose family name is the whole board, fitted with `<equipment>`, generates `<family>`, `<equipment>` and `<family>-<equipment>` — family and identity coincide, since there is no separate board slot to name, so there is no separate identity label to duplicate.
- A non-board service runner (a build box, a CUDA host, the Yocto builder) carries capability labels only, with no family/identity/equipment structure at all.

**Every label reference is written exactly as GitHub reports it**, so a reader can compare against `gh api .../runners` without translating. New custom labels are lowercase and hyphen-separated. A small number of pre-existing labels keep whatever casing they were first registered with, because GitHub's organisation-wide label registry fixes a label's casing at first creation and the API cannot change it thereafter — check `gh api orgs/EdgeFirstAI/actions/runners` before introducing a label that might collide on casing with one already in use. GitHub's auto-assigned labels are written as GitHub capitalises them: `self-hosted`, `Linux`, `X64`, `ARM64`, `Windows`, `macOS`. Matching is case-insensitive throughout, so none of this costs anything at runtime.

**The bare identity label matches any board of that identity regardless of BSP** — boards of the same identity may deliberately run different BSPs, so a caller using the bare label is robust to that variance by design. A pinned label targets one specific BSP by appending its numeric version to the identity. Version tails are numeric so they never read as an equipment suffix.

**The compound equipment label exists only when the equipment is optional for that identity.** Some units of a given board carry an accelerator and some don't, so a caller can ask for either the family or specifically the equipped ones. Equipment that's intrinsic to every unit of a board (never optional) doesn't earn a compound label — the bare board identity plus the bare capability label is enough, since a compound of the two would never narrow anything beyond what the board identity already does.

`provision_runner.sh`'s `BOARD_FAMILIES` and `CAPABILITY_SUFFIXES` arrays are this convention's vocabulary in code form — extend them there when a new family or equipment type is provisioned, and see Confluence for the fleet's actual current composition.

## Creating a group

```bash
gh api --method POST orgs/EdgeFirstAI/actions/runner-groups \
  -f name=boards -F visibility=all -F allows_public_repositories=true
```

Then add it to `runners.json` and run the apply script.
