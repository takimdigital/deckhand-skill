# repo-presence — the one-time "nice repo" pass (ref 40 §6b)

Every repo a user opens should look deliberate: a real README, an honest LICENSE, correct
metadata, a first release. This kit makes that mechanical — **the agent fills one JSON, the
script renders the rest.** Nobody hand-builds a README again.

## Use (at the first release, or any time the repo's face drifts)

```bash
cp templates/ops/repo-presence/repo.example.json repo.json   # then fill it — facts only, our style
py ops/scripts/repo_presence.py init repo.json --dir <project> --dry-run   # preview
py ops/scripts/repo_presence.py init repo.json --dir <project> --gh        # write + set gh description/topics
```

Then finish with the release (ref 40 §6b): `git tag vX.Y.Z && git push origin vX.Y.Z && gh release create ...`

## What it renders

| File | From | Notes |
|---|---|---|
| `README.md` | `README.template.md` | sections without content are dropped; missing required fields fail loudly |
| `LICENSE` | `LICENSE.proprietary.txt` | only when `license: "proprietary"`; upstream MIT notice retained when `license_derived_from` is set |
| `package.json` | your JSON fields | only `name`/`version`/`description`/`license` are touched |
| GitHub | `--gh` | `repo set-default` + description + topics (uses `repo` field `owner/name`) |

## Rules (baked in)

- Facts only, present tense; ≤ 8 feature bullets; no internal narration, no promises the product doesn't keep.
- Version in `package.json` == the newest tag; the README's status line says what's live **today**.
- Public repo? Set `license` to `mit`/`apache-2.0` and delete `license_derived_from` if not applicable.
- Re-run only when the face changed — don't churn the README every deploy.
- Repo with a second remote (a template kept as `upstream`)? `gh` may aim at upstream — the kit's printed
  `gh repo set-default <repo>` step fixes that permanently; or pass `-R <repo>` on release commands.
