# Self-hosted runner groups

Access lists, not machines. The group controls which repositories may use a runner; labels describe what the machine has. Desired state lives in [`runners.json`](runners.json) and is applied by [`apply-runners.sh`](apply-runners.sh) — edit the JSON in a pull request rather than clicking through organisation settings, which is how the fleet drifted from this document in the first place.

## Applying

```bash
gh auth refresh -h github.com -s admin:org
.github/rulesets/apply-runners.sh --dry-run   # review
.github/rulesets/apply-runners.sh             # apply
```

## The fleet

Every machine is a dedicated box running a persistent, service-installed runner (`svc.sh`). **One runner instance per device is policy**, and with no workflow-level concurrency group on the board lane it is the only guarantee that a physical board runs one job at a time. Ephemeral runners are a future consideration, most likely a k8s cluster.

| Runner | Group | Labels | Notes |
| --- | --- | --- | --- |
| `ubuntubuild` | `build-x86` | `self-hosted,Linux,X64,build` | General Linux build capacity; answers `runner-class-linux: fleet` |
| `JENKINSW10BUILD` | `windows` | `self-hosted,X64,Windows,build` | Answers `runner-class-windows: fleet`. Not `d3d11`: it has no GPU |
| `mltrain-02` | `gpu-cuda` | `self-hosted,Linux,X64,CUDA` | GPU-only; answers `lanes: gpu` |
| `mltrain-03` | `gpu-cuda` | `self-hosted,Linux,X64,CUDA` | GPU-only |
| `mltrain-04` | `yocto` | `self-hosted,Linux,X64,Yocto` | Shared with Jenkins during the Yocto migration |
| `imx8mpevk-08` | `boards` | `…,ARM64,imx8mp,imx8mp-evk,imx8mp-evk-6.12.34-2.1.0` | Plus legacy `nxp-imx8mp-latest` and `nxp-imx8mp-6.12.34-2.1.0` |
| `imx8mpevk-04` | `boards` | `…,ARM64,imx8mp,imx8mp-evk,nxp-imx8mp-latest` | Plus legacy `imx8mpevk` |

`mac` exists and is empty; no macOS machine is provisioned. The same is true of `linux-arm`: `resolve_lanes.py`'s `FLEET` tuple for it names a machine that does not exist, so `runner-class-linux-arm: fleet` queues until timeout, silently.

`larger-runners` lists `hal` and `packaging` but **contains no runners** — the billed GitHub larger runners are all still in `Default`, so the restriction this table once implied is not in force. Applying it is the closing ticket of the CI epic, once the main repositories have migrated onto internal runners; `ara2-rs` must be added to the list first, and `packaging` has not migrated at all.

## Label convention

Every board runner carries labels at three granularities, because the board lane's `runs-on` takes a single label and cannot express a conjunction. A caller picks the granularity it needs.

**Processor family**, bare, carried by every board of that family: `imx8mp`, `imx95`, `rpi5`, `rk3855`, `orin`. `boards: imx8mp` means any i.MX 8M Plus carrier.

**Board identity** — the shortest unambiguous board name, no vendor prefix. SoC-prefixed only where the board name alone is ambiguous across SoCs:

```text
imx8mp-frdm      imx95-frdm       orin-nano    rpi5
imx8mp-evk       imx95-frdm-pro   orin-agx     rpi5-hailo8l
imx8mp-phytec    imx95-evk        rk3855       imx8mp-maivin
imx8mp-ezurio    imx95-phytec                  imx8mp-raivin
imx8mp-verdin    imx95-verdin                  imx8mp-frdm-ara240
```

The suffix slot carries a board variant (`-pro`) or fitted equipment (`-ara240`, `-hailo8l`).

**The bare board label is the current BSP.** A pinned BSP appends its numeric version: `imx8mp-evk-6.12.34-2.1.0`. Version tails are numeric so they never read as an equipment suffix.

**Capability labels** are bare and orthogonal, carried in addition: `hailo8l`, `ara240`, `CUDA`. So `boards: hailo8l` targets any Hailo-equipped board across families. Jetsons may carry `CUDA` safely — the GPU lane tuple is `x64`-gated and `X64`/`ARM64` are auto-assigned.

Legacy labels (`nxp-imx8mp-latest`, `imx8mpevk`) are retained until the epic wraps up, because `hal` pins the shared workflow at a SHA and names `nxp-imx8mp-latest` directly.

## Creating a group

```bash
gh api --method POST orgs/EdgeFirstAI/actions/runner-groups \
  -f name=boards -F visibility=selected -F allows_public_repositories=true
```

Then add it to `runners.json` and run the apply script.
