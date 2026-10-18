# Harborforge Lab — Independent Skill Copy

**Status:** experimental, initial isolation branch. **Source:** Deckhand v2.5.0, `main` commit `b111dc0865deef105293ecc2d25b6a50da8e63af`.

This branch holds a full Git-object copy of the Deckhand skill in `skills/harborforge/` while leaving `main` unchanged. Original files under `skills/deckhand/` are retained in this branch for comparison and regression testing.

## Ownership and safety

This repository is still owned by the GitHub account `takimdigital`. ChatGPT can maintain the isolated branch when authorized but **cannot own a GitHub account or independently persist as a maintainer**. No commits on this branch modify `main`.

**Do not install Harborforge alongside Deckhand or run it against any existing Deckhand project yet.** The copy has a distinct skill name, but internal `dh`, `.deckhand/` and persistent-state identifiers remain inherited from Deckhand. Full namespace separation, parallel installation tests and a new public repository are future release gates.

## First source changes

1. Fixed deploy-hook state mismatch: current `app_uuid` plus legacy `app` are recognized.
2. Reject unsupported bot runners for workflow-only audits, instead of creating invalid cron/Hermes wrappers.
3. Expose `generated_unverified` status for bot scaffolding: creating a script is not proof of scheduling or delivery.
4. Propagate nonzero `SystemExit` from the generated script-only Hermes wrapper.
5. Renamed skill frontmatter to `harborforge`, normalized provider-neutral metadata, and retained optional Try-on.
6. Added regression coverage for the current and legacy deployment-app keys.

## Required next work

- Replace inherited local paths, project state directory, home directory, CLI name, hook markers, temp dirs and data namespace with Harborforge-specific paths, with migration-safe fallback only where explicitly requested.
- Build platform-neutral scheduler capabilities and a real check → escalation → verification contract; Hermes stays an optional adapter.
- Prove installer operation on Linux/macOS/Windows with `HERMES_HOME` unset.
- Run copied Python, Node, and end-to-end suites. No successful CI or runtime result is claimed yet.
- Publish a separately owned repository only when its owner creates one or grants creation capability. Do not merge this branch into Deckhand main.

## How to obtain full source

`git clone --branch harborforge-lab --single-branch https://github.com/takimdigital/deckhand-skill.git`

The experimental copy is in `skills/harborforge/`. Its `SKILL.md` should not yet be installed as a production skill.
