# Self-hosted runner groups

Access lists, not machines. Machines are registered by the scripts in `.github/runners/` (EDGEAI-1577). Labels describe capability; the group controls which repositories may use them.

## Creating a group

Requires org admin (`gh auth refresh -h github.com -s admin:org`):

```bash
gh api --method POST orgs/EdgeFirstAI/actions/runner-groups \
  -f name=boards -F visibility=selected -F allows_public_repositories=true
```

Then add repository IDs with:

```bash
gh api --method PUT orgs/EdgeFirstAI/actions/runner-groups/{id}/repositories \
  --input repos.json
```

## Groups

All groups use `visibility=selected` and `allows_public_repositories=true`.

| Group | Labels | Notes |
| --- | --- | --- |
| `boards` | on-target imx8 / similar | Empty repo list until hardware CI callers exist |
| `build-x86` | self-hosted, linux, x64, build | |
| `gpu-cuda` | self-hosted, linux, x64, cuda | |
| `mac` | self-hosted, macos, arm64, metal | |
| `windows` | self-hosted, windows, x64, d3d11 | |
| `larger-runners` | GitHub larger hosted runners | Restricted to hal and packaging |
