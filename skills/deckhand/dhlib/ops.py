"""OPERATE: bots that run the business while the owner sleeps — suggested from what was built.

`suggest` ranks data/bots.json against the brief (shape, features) and what is deployed.
`add <id> --runner github|cron` installs it: generic bots are real scripts (ops/bots/*.py, stdlib)
plus a schedule; app bots get a spec + skeleton the agent completes against THIS app's data model.
A schedule is verified only by its own trigger — the output says exactly how.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .util import DATA, SKILL, TEMPLATES, DhError, read_json


def catalog() -> list:
    return (read_json(DATA / "bots.json", {}) or {}).get("bots", [])


def suggest(root: Path) -> dict:
    root = Path(root)
    brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
    shape = brief.get("shape")
    feats = set(brief.get("features") or [])
    deployed = bool((read_json(root / ".deckhand" / "deploy.json", {}) or {}).get("url"))
    installed = {p.stem.replace("_", "-") for p in (root / "ops" / "bots").glob("*.py")} if (root / "ops" / "bots").exists() else set()
    out = []
    for b in catalog():
        fits = b.get("fits")
        if fits != "*" and shape not in (fits or []):
            continue
        req = set(b.get("requires") or []) - {"database", "email", "inventory"}
        if req and not req <= feats:
            continue
        out.append({"id": b["id"], "title": b["title"], "kind": b["kind"], "why": b["why"], "schedule": b["schedule"],
                    "needs": b.get("needs", []), "installed": b["id"] in installed,
                    "priority": b.get("priority", 5 if b["kind"] == "app" else 3)})
    out.sort(key=lambda x: (x["installed"], x["priority"], x["id"]))
    return {"shape": shape, "deployed": deployed, "bots": out,
            "recommendation": [x["id"] for x in out if not x["installed"]][:4],
            "note": None if deployed else "bots watch a live site — deploy first, or point SITE_URLS at the preview"}


def add(root: Path, bot_id: str, runner: str = "github") -> dict:
    root = Path(root)
    b = next((x for x in catalog() if x["id"] == bot_id), None)
    if not b:
        raise DhError("NO_SUCH_BOT", bot_id)
    if runner not in ("github", "cron", "local", "hermes"):
        raise DhError("BAD_RUNNER", "runner: github | cron | local | hermes")
    if runner == "hermes" and not os.environ.get("HERMES_HOME"):
        raise DhError("NOT_HERMES", "HERMES_HOME is not set: --runner hermes is for a Hermes session (use --runner github or cron elsewhere)")
    bots = root / "ops" / "bots"
    bots.mkdir(parents=True, exist_ok=True)
    written = []
    shutil.copy(TEMPLATES / "bots" / "notify.py", bots / "notify.py")
    written.append("ops/bots/notify.py")
    script = None
    if b["kind"] == "generic" and b.get("script") and not b.get("workflow_only"):
        src = (TEMPLATES / "bots" / b["script"]).resolve()
        script = bots / Path(b["script"]).name
        shutil.copy(src, script)
        written.append(str(script.relative_to(root)))
    elif b["kind"] == "app":
        name = bot_id.replace("-", "_") + ".py"
        script = bots / name
        if not script.exists():
            script.write_text(
                f'#!/usr/bin/env python3\n"""{b["title"]} — APP-SPECIFIC BOT (complete against this app\'s data model).\n\n'
                f'SPEC: {b["spec"]}\nWHY: {b["why"]}\nRULES: read-only DB user; idempotent (state file); one message via notify.send();\n'
                f'secrets from env only. Remove the NotImplementedError when done and run it once by hand.\n"""\n'
                "import os, sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).resolve().parent))\n"
                "from notify import send  # noqa: E402\n\n\ndef main() -> int:\n"
                f'    raise NotImplementedError("{bot_id}: implement the SPEC above against this app")\n\n\n'
                'if __name__ == "__main__":\n    sys.exit(main())\n', encoding="utf-8")
            written.append(str(script.relative_to(root)))
    env_names = ["SITE_URLS", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL", "NOTIFY_WEBHOOK_URL", "SMTP_URL"]
    if bot_id == "watchdog":
        env_names += ["COOLIFY_URL", "COOLIFY_TOKEN", "VPS_SSH"]
    verify = ""
    hermes_cron = None
    if runner == "github":
        wf = root / ".github" / "workflows" / f"deckhand-{bot_id}.yml"
        wf.parent.mkdir(parents=True, exist_ok=True)
        if b.get("workflow_only"):
            steps = ("      - uses: actions/setup-node@v4\n        with:\n          node-version: 22\n"
                     "      - run: npm audit --audit-level=high\n")
        else:
            env = "\n".join(f"          {n}: ${{{{ {'vars' if n in ('SITE_URLS', 'COOLIFY_URL') else 'secrets'}.{n} }}}}" for n in env_names)
            steps = f"      - run: python ops/bots/{script.name}\n        env:\n          BOT_STATE_DIR: .bot-state\n{env}\n"
        wf.write_text((TEMPLATES / "bots" / "workflow.yml").read_text(encoding="utf-8").replace("{{ID}}", bot_id)
                      .replace("{{TITLE}}", b["title"]).replace("{{CRON}}", b["schedule"]).replace("{{STEPS}}", steps.rstrip("\n")), encoding="utf-8")
        written.append(str(wf.relative_to(root)))
        verify = f"git push; gh variable set SITE_URLS --body https://…; gh secret set TELEGRAM_BOT_TOKEN …; gh workflow run deckhand-{bot_id}.yml; gh run list -w deckhand-{bot_id}.yml -L 1"
        note = "alert state persists through actions/cache (.bot-state), so only changes are reported"
    elif runner == "hermes":
        slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "site"
        wrapper = Path(os.environ["HERMES_HOME"]) / "scripts" / f"deckhand-{slug}-{bot_id}.py"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        text = (TEMPLATES / "bots" / "hermes_cron.py").read_text(encoding="utf-8")
        for k, v in (("__SKILL__", str(SKILL)), ("__PROJECT__", str(root.resolve())), ("__BOT__", str(script.resolve()) if script else ""),
                     ("__NAMES__", env_names)):
            text = text.replace(k, repr(v))
        wrapper.write_text(text, encoding="utf-8")
        written.append(str(wrapper))
        hermes_cron = {"action": "create", "name": f"deckhand {root.name} {bot_id}", "schedule": b["schedule"],
                       "script": wrapper.name, "no_agent": True}
        from . import guide
        row = guide.harness_row("hermes")            # the wording of Hermes' tools lives in data/harness.json, not here
        verify, note = row.get("cron_verify", ""), row.get("cron_note", "")
    else:
        line = f"{b['schedule']} cd /opt/deckhand-bots && set -a && . ./bots.env && set +a && python3 {script.name if script else ''} >> bot.log 2>&1"
        verify = (f"scp -r ops/bots root@$VPS_IP:/opt/deckhand-bots && ssh root@$VPS_IP '(crontab -l; echo \"{line}\") | crontab -' "
                  f"&& ssh root@$VPS_IP 'cd /opt/deckhand-bots && set -a && . ./bots.env && python3 {script.name if script else ''}'")
        note = "create /opt/deckhand-bots/bots.env on the server (chmod 600) with: " + ", ".join(env_names)
    return {"bot": bot_id, "kind": b["kind"], "written": written, "schedule": b["schedule"], "runner": runner,
            "env": env_names, "verify_by_its_own_trigger": verify, "note": note,
            **({"hermes_cron": hermes_cron} if hermes_cron else {}),
            "todo": "implement the SPEC in the skeleton, run once by hand, then verify the schedule" if b["kind"] == "app" else None}
