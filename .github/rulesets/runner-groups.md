# Self-hosted runner groups (access lists, not machines).
#
# Create with org admin (gh auth refresh -h github.com -s admin:org):
#
#   gh api --method POST orgs/EdgeFirstAI/actions/runner-groups \
#     -f name=boards -F visibility=selected -F allows_public_repositories=true
#
# Then add repository IDs with:
#   gh api --method PUT orgs/EdgeFirstAI/actions/runner-groups/{id}/repositories \
#     --input repos.json
#
# Groups (visibility=selected, allows_public_repositories=true):
#   boards          on-target imx8 / similar labels; empty repo list until
#                   hardware CI callers exist
#   build-x86       self-hosted, linux, x64, build
#   gpu-cuda        self-hosted, linux, x64, cuda
#   mac             self-hosted, macos, arm64, metal
#   windows         self-hosted, windows, x64, d3d11
#   larger-runners  GitHub larger hosted runners; restricted to hal and packaging
#
# Machines are registered by the scripts in .github/runners/ (EDGEAI-1577).
# Labels describe capability; the group controls which repositories may use them.
