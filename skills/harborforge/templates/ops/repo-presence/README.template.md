# {{NAME}}

**{{TAGLINE}}**

**Live:** {{LIVE_URL}} · **Version:** {{VERSION}} ([releases](../../releases)) · **Runbook:** [OPS.md](OPS.md)

{{INTRO}}

<!--if:FEATURES-->
## Features

{{FEATURES}}

<!--/if:FEATURES-->
## Stack

{{STACK}}

<!--if:SETUP_COMMANDS-->
## Local development

```bash
{{SETUP_COMMANDS}}
```

{{ENV_NOTE}}

<!--/if:SETUP_COMMANDS-->
<!--if:ENV_TABLE-->
Environment variables (names only — never commit values):

{{ENV_TABLE}}

<!--/if:ENV_TABLE-->
<!--if:LAYOUT-->
## Project layout

```
{{LAYOUT}}
```

<!--/if:LAYOUT-->
## Deploy & ops

{{DEPLOY_NOTES}}

- **Runbook** — live URL, environment variables, backups, deploy provenance: [`OPS.md`](OPS.md)
<!--if:CI_LINE-->
- **CI** — {{CI_LINE}}
<!--/if:CI_LINE-->
- **Releases** — runtime changes are tagged and released (Releases tab); docs-only changes aren't

<!--if:STATUS-->
## Status

{{STATUS}}
<!--/if:STATUS-->
