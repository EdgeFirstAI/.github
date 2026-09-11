# AI assistant guidelines — <PROJECT>

Canonical process, CI tiers, runner policy and release chain:

https://github.com/EdgeFirstAI/.github/blob/main/.github/copilot-instructions.md

Keep this file for project-specific notes only (workspace layout, test commands,
hardware, platform `cfg`). Do not duplicate branch/commit/PR/release rules here.

## Project-specific

### Layout

- TODO: crates/, src/, tests/

### Tests

- Unit: `cargo nextest run --workspace --locked`
- Hardware: ignored by default; run on-target via `ci:hardware`

### Platform notes

- TODO
