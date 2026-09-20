# Self-hosted runner groups

Organisation, not access control. Labels describe what a machine has and are what a workflow selects on; the group just gathers runners under a name. **No group is scoped to a repository list.** Every group is `visibility: all`, reachable by every repository in the organisation, and `runners.json` has no way to express anything else. Desired state lives in [`runners.json`](runners.json) and is applied by [`apply_runners.py`](../scripts/apply_runners.py) — edit the JSON in a pull request rather than clicking through organisation settings, which is how the fleet drifted from this document in the first place.

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

## Applying

```bash
gh auth refresh -h github.com -s admin:org
python3 .github/scripts/apply_runners.py --dry-run   # review
python3 .github/scripts/apply_runners.py             # apply
```

## Registering a runner

**Register with no custom labels.** Do not pass `--labels` to `config.sh` — let the agent assert only its defaults (`self-hosted` plus OS and architecture). Every custom label is added afterwards through the API, by `apply_runners.py` from `runners.json`. That way the converger owns every custom label a runner has: a board that is re-provisioned or re-registered comes back label-less, and the converger restores its identity entirely from the declarative file rather than from whatever was typed at the console.

`mltrain-02`, `mltrain-03` and `mltrain-04` predate this rule and were registered with `--labels`.

## The fleet

Every machine is a dedicated box running a persistent, service-installed runner (`svc.sh`). **One runner instance per device is policy**, and with no workflow-level concurrency group on the board lane it is the only guarantee that a physical board runs one job at a time. Ephemeral runners are a future consideration, most likely a k8s cluster.

| Runner | Group | Labels | Notes |
| --- | --- | --- | --- |
| `ubuntubuild` | `build-x86` | `self-hosted,Linux,X64,build` | General Linux build capacity; answers `runner-class-linux: fleet` |
| `JENKINSW10BUILD` | `windows` | `self-hosted,X64,Windows,build` | Answers `runner-class-windows: fleet`. Not `d3d11`: it has no GPU |
| `mltrain-02` | `gpu-cuda` | `self-hosted,Linux,X64,CUDA` | GPU-only; answers `lanes: gpu`. Casing predates the lowercase convention |
| `mltrain-03` | `gpu-cuda` | `self-hosted,Linux,X64,CUDA` | GPU-only. Casing predates the lowercase convention |
| `mltrain-04` | `yocto` | `self-hosted,Linux,X64,Yocto` | Shared with Jenkins during the Yocto migration. Casing predates the lowercase convention |
| `imx8mpevk-08` | `boards` | `…,ARM64,imx8mp,imx8mp-evk,imx8mp-evk-6.12.34-2.1.0` | Plus legacy `nxp-imx8mp-latest` and `nxp-imx8mp-6.12.34-2.1.0` |
| `imx8mpevk-04` | `boards` | `…,ARM64,imx8mp,imx8mp-evk` | Plus legacy `imx8mpevk`. Does not carry `nxp-imx8mp-latest` |

`mltrain-02` and `mltrain-03` must have `git-lfs` preinstalled: the CI user has no passwordless sudo on either box, so the GPU lane requires it rather than installing it.

**Accepted risk on `mltrain-04`:** `yocto-build.yml`'s `concurrency` group coordinates GitHub Actions jobs within the calling repository only. A Jenkins bitbake on the same box is invisible to it and can still overlap a GitHub-triggered build, despite the RAM and sstate contention that group exists to prevent. The mitigation is completing the Yocto migration off Jenkins, not a lock; there is no cross-scheduler lock available.

`imx8mpevk-04` is in `boards` and carries the family and identity labels, but not `nxp-imx8mp-latest` — the deprecated label `hal` still targets. The two EVKs deliberately run different BSPs, so that legacy label stays on `imx8mpevk-08` alone rather than extending it to a second board with a different BSP than the one it names. `hal`'s move to `imx8mp-evk` retires the need for it and is robust to the BSP variance by design.

`mac` exists and is empty; no macOS machine is provisioned. The same is true of `linux-arm`: `resolve_lanes.py`'s `FLEET` tuple for it names a machine that does not exist, so `runner-class-linux-arm: fleet` queues until timeout, silently.

`larger-runners` **contains no runners** — the billed GitHub larger runners are all still in `Default` — and it is no longer scoped either. Restricting billed capacity is the closing ticket of the CI epic, once the main repositories have migrated onto internal runners. Whatever mechanism that ticket picks, it starts from an unrestricted state rather than from the stale `hal`/`packaging` list that used to sit here and enforced nothing.

## Label convention

Labels are generative, not a maintained list: a runner is described by four facts, and its label set follows from them. That is what will let provisioning derive labels later instead of someone maintaining a table.

- **family** — the processor family, e.g. `imx8mp`, `imx95`, `rpi5`, `rk3855`, `orin`.
- **board** — the board within that family, e.g. `frdm`, `evk`. Omitted when the family name is the whole board (a Raspberry Pi 5 has no separate board slot).
- **equipment** — zero or more fitted extras, e.g. `hailo8l`, `ara240`.
- **bsp** — the pinned BSP version, when known, e.g. `6.12.34-2.1.0`.

| Label | Form | Example |
| --- | --- | --- |
| family | `<family>` | `imx8mp` |
| identity | `<family>-<board>` | `imx8mp-frdm` |
| pinned BSP | `<identity>-<bsp>` | `imx8mp-frdm-6.12.34-2.1.0` |
| equipment, bare | `<equipment>` | `ara240` |
| equipment, compound | `<identity>-<equipment>` | `imx8mp-frdm-ara240` |

Worked examples:

- An `imx8mp-frdm` fitted with an ara240 generates `imx8mp`, `imx8mp-frdm`, `ara240` and `imx8mp-frdm-ara240`, plus a pinned-BSP label once the BSP is known.
- An `rpi5` fitted with a Hailo generates `rpi5`, `hailo8l` and `rpi5-hailo8l` — family and identity coincide, since the family name is the whole board, so there is no separate identity label to duplicate.
- A non-board service runner (a build box, a CUDA host, the Yocto builder) carries capability labels only: `build`, `CUDA`, `Yocto`.

Board identities in use, SoC-prefixed only where the board name alone is ambiguous across SoCs:

```text
imx8mp-frdm      imx95-frdm       orin-nano    rpi5
imx8mp-evk       imx95-frdm-pro   orin-agx     rpi5-hailo8l
imx8mp-phytec    imx95-evk        rk3855       imx8mp-maivin
imx8mp-ezurio    imx95-phytec                  imx8mp-raivin
imx8mp-verdin    imx95-verdin                  imx8mp-frdm-ara240
```

**Every label reference is written exactly as GitHub reports it**, so a reader can compare a file against `gh api .../runners` without translating. New custom labels we create are lowercase and hyphen-separated. `CUDA` and `Yocto` are the exception and keep their registered casing, because GitHub's organisation-wide label registry fixes a label's casing at first creation and the API cannot change it thereafter. GitHub's auto-assigned labels are written as GitHub capitalises them: `self-hosted`, `Linux`, `X64`, `ARM64`, `Windows`, `macOS`. Matching is case-insensitive throughout, so none of this costs anything at runtime.

**The bare identity label matches any board of that identity regardless of BSP** — boards of the same identity may deliberately run different BSPs, so a caller using the bare label is robust to that variance by design. A pinned label targets one specific BSP by appending its numeric version: `imx8mp-evk-6.12.34-2.1.0`. Version tails are numeric so they never read as an equipment suffix.

**The compound equipment label exists only when the equipment is optional for that identity.** `rpi5-hailo8l` earns its place because some Pi 5s carry the Hailo HAT and some do not, so a caller can ask for either the family or specifically the Hailo-equipped ones. A Jetson's CUDA is intrinsic to the board, not optional equipment, so `orin-nano` plus the bare `CUDA` label is enough and `orin-nano-cuda` would be a compound that never narrows anything.

Legacy labels (`nxp-imx8mp-latest`, `imx8mpevk`) are retained until the epic wraps up, because `hal` pins the shared workflow at a SHA and names `nxp-imx8mp-latest` directly. They predate this convention and are not remade to fit it.

## Creating a group

```bash
gh api --method POST orgs/EdgeFirstAI/actions/runner-groups \
  -f name=boards -F visibility=all -F allows_public_repositories=true
```

Then add it to `runners.json` and run the apply script.
