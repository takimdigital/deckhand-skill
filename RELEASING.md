# Releasing

1. Tests green: `python3 -m unittest discover -s skills/deckhand/tests` · `python3 -m pytest skills/deckhand/ops/tests -q` · `node --test skills/deckhand/tryon/test/*.test.mjs`
2. Bump the version in `skills/deckhand/SKILL.md`, the README badge and a new top entry in `CHANGELOG.md`.
3. `python3 scripts/version_check.py --tag vX.Y.Z` → VERSIONS OK.
4. `python3 scripts/leak_sweep.py` (private terms in `~/.deckhand/private-terms.txt`) → clean.
5. Rebuild the component catalog when registries changed: `node skills/deckhand/tryon/catalog-build.mjs` (network).
6. Write `docs/releases/vX.Y.Z.md`: first line `# vX.Y.Z — <title>`, then ≤ 8 user-facing bullets.
7. Publish: push the tag (`git tag vX.Y.Z <main sha> && git push origin vX.Y.Z`), or run the `release` workflow
   (Actions → release → Run workflow → tag). `.github/workflows/release.yml` re-checks the versions against the tag
   and creates the GitHub release from that file (it refuses when the file or a version is missing, when the
   commit is not on main, or when CI is not green on it for both Ubuntu and Windows).
