"""dh — the Deckhand control plane. One JSON object per command on stdout; exit 0 = ok, 1 = check
failed / refused, 2 = usage. Run `dh next` whenever unsure: it prints the one next step."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .util import DH, SKIPPED, DhError, SKILL, TRYON, emit, locked, project_root, read_json, runnable_obj, write_json
from . import state as STATE
from . import resume as RESUME


def _root(a) -> Path:
    return project_root(getattr(a, "project", None))


def _kv(pairs):
    out = {}
    for p in pairs:
        if "=" not in p:
            raise DhError("BAD_PAIR", f"expected key=value, got {p!r}")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    return out


# own: the owner's business · client: built for a client · product: a boilerplate sold to many (demo company in the seed,
# the buyer's facts in settings, a product kit checked by `dh verify`)
BRIEF_CHOICES = {"deliverable": ("own", "client", "product")}
LIST_KEYS = ("languages", "demo.paths", "features", "assumed", "template_names", "brand.social", "seo.keywords", "seo.locations", "seo.profiles",
             "seo.photos", "seo.local.hours")


def cmd_brief(a):
    root = _root(a)
    path = root / ".deckhand" / "brief.json"
    if a.action == "set":
        with locked(root):                               # parallel `brief set` calls: each one merges into the latest file
            return _brief_set(a, path)
    return _brief_load(path)


def _brief_load(path: Path) -> dict:
    if path.exists():
        b = read_json(path, None, expect=dict)
        if b is None:                                    # never write a fresh brief over a file we could not read
            raise DhError("BRIEF_CORRUPT", f"{path} is empty, truncated or not a JSON object — restore it (`git checkout .deckhand/brief.json`) "
                          "or move it aside, then `dh brief set …` starts a new one; nothing was overwritten")
        return b or json.loads((SKILL / "templates" / "brief.json").read_text(encoding="utf-8"))
    return json.loads((SKILL / "templates" / "brief.json").read_text(encoding="utf-8"))


def _brief_set(a, path: Path) -> dict:
    b = _brief_load(path)
    if a.action == "set":
        for k, v in _kv(a.pairs).items():
            if k in BRIEF_CHOICES and v not in BRIEF_CHOICES[k]:
                raise DhError("BAD_VALUE", f"{k} must be one of {', '.join(BRIEF_CHOICES[k])}")
            from .redact import scrub_text
            v = scrub_text(v)
            val = [x.strip() for x in v.split(",") if x.strip()] if k in LIST_KEYS else v
            cur = b
            parts = k.split(".")
            if not all(parts):
                raise DhError("BAD_KEY", f"'{k}' is not a brief key (name.sub=value, no empty parts)")
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
                if not isinstance(cur, dict):
                    raise DhError("BAD_KEY", f"'{k}': {p} already holds a value, not a group of keys")
            cur[parts[-1]] = val
        write_json(path, b)
    return b


def cmd_workflow(a, root: Path):
    from . import workflow as WF
    act = a.action
    if act == "query":
        brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
        opts = {"deliverable": a.deliverable, "industry": a.industry, "shape": a.shape, "harness": a.harness, "os": a.os, "min_level": a.min_level,
                "features": [x.strip() for x in (a.features or "").split(",") if x.strip()] or None}
        return WF.query(brief, opts, a.top, refresh=a.refresh)
    if act == "list":
        return {"workflows": [{k: r.get(k) for k in ("id", "version", "title", "source", "level", "green", "runs", "steps")} for r in WF.rows(a.refresh)]}
    if act == "sync":
        return WF.sync()
    if act == "use":
        if not a.target:
            raise DhError("USAGE", "dh workflow use <ref> [--set name=value] [--accept]")
        return WF.use(root, a.target, accept=a.accept, sets=_kv(a.set))
    if act == "status":
        return WF.progress(root) or {"pinned": None, "next": f"{DH} workflow query"}
    if act == "todo":
        return WF.todo(root, a.format, a.phase)
    if act == "step":
        if not a.target or not a.state:
            raise DhError("USAGE", "dh workflow step <ID> done|skip [--why \"…\"]")
        return WF.step(root, a.target, a.state, a.why or "")
    if act == "show":
        wf, src = WF.load(a.target) if a.target else WF._pinned_wf(root)[0:1] + ("pinned",)
        vals = WF.params_for(wf, root if (root / ".deckhand").exists() else None)
        if a.format == "md":
            return {"ref": f"{src}:{wf['id']}@{wf.get('version', 1)}", "markdown": WF.render_md(wf, vals, a.phase)}
        return {"ref": f"{src}:{wf['id']}@{wf.get('version', 1)}", "level": WF.level(wf), "workflow": wf}
    if act == "lint":
        if not a.target:
            raise DhError("USAGE", "dh workflow lint <ref|file.json>")
        wf, src = WF.load(a.target)
        r = WF.lint(wf, strict=src != "mine")
        if not r["ok"]:
            raise DhError("WORKFLOW_INVALID", f"{len(r['errors'])} errors", **r)
        return r
    if act == "new":
        if not a.from_run:
            raise DhError("USAGE", "dh workflow new --from-run [--id ID] [--title T]   (extracts this project's run as a draft in your pool)")
        return WF.new_from_run(root, a.id, a.title)
    if act == "save":
        if a.from_autopsy:
            from . import wfautopsy as WA
            return WA.workflow_save(root, a.from_autopsy, [x.strip() for x in a.proposals.split(",") if x.strip()], public=a.public, wid=a.id)
        if not a.target:
            raise DhError("USAGE", "dh workflow save <file.json> [--public]  ·  dh workflow save --from-autopsy ID --proposals P1,P3 [--public]")
        wf, _ = WF.load(a.target)
        return WF.save(wf, "public" if a.public else "mine")
    if act == "publish":
        if not a.target:
            raise DhError("USAGE", "dh workflow publish <ref>")
        return WF.publish_bundle(WF.load(a.target)[0])
    raise DhError("USAGE", act)


def cmd_slop(a, root: Path):
    from . import slop as SLOP
    act = a.action
    in_project = (root / ".deckhand").is_dir() or (root / "package.json").exists()
    proj = root if in_project else None
    if act == "check":
        text = sys.stdin.read() if a.text == "-" else a.text
        r = SLOP.check(proj, paths=a.target, text=text, url=a.url, lang=SLOP.lang_code(a.lang) if a.lang else None)
        if r["verdict"] == "slop":
            raise DhError("SLOP", "this copy reads as written by a model — rewrite what the hits list (each has a fix)", **r)
        return r
    if act == "brief":
        langs = [SLOP.lang_code(a.lang)] if a.lang else (SLOP._langs(proj) if proj else []) or ["en"]
        return {"briefs": [SLOP.brief(x, proj) for x in langs]}
    if act == "langs":
        return SLOP.langs()
    if act == "lint":
        files = [Path(x) for x in a.target] or list(SLOP.shipped().values())
        rows = [{"file": str(f), **SLOP.lint(read_json(f, {}) or {})} for f in files]
        bad = [r for r in rows if not r["ok"]]
        if bad:
            raise DhError("PACK_INVALID", f"{len(bad)} pack(s) fail their own test", packs=rows)
        return {"packs": rows}
    if act == "add":
        if not a.lang:
            raise DhError("USAGE", "dh slop add \"word or phrase\" --lang fr [--buzz] [--phrase] [--fix \"plainer word\"]")
        return SLOP.add(" ".join(a.target), SLOP.lang_code(a.lang), phrase=a.phrase, buzz=a.buzz, fix=a.fix)
    if act == "allow":
        if not a.target:
            raise DhError("USAGE", "dh slop allow \"brand or trade word\"")
        return SLOP.allow(root, " ".join(a.target))
    if act == "export":
        if not a.lang:
            raise DhError("USAGE", "dh slop export --lang fr")
        return SLOP.export(SLOP.lang_code(a.lang))
    raise DhError("USAGE", act)


def tryon_argv(rest: list, root) -> list:
    """`dh tryon flags report …` → the engine's argv. `--project` goes last: after the command it would split
    `flags report` (the engine reads its action at argv[1])."""
    rest = list(rest[1:] if rest and rest[0] == "--" else rest)
    return rest if "--project" in rest else rest + ["--project", str(root)]


class _Usage(Exception):
    def __init__(self, message: str, usage: str):
        super().__init__(message)
        self.message, self.usage = message, usage


class _Help(Exception):
    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


class DhParser(argparse.ArgumentParser):
    """argparse that never prints or exits: a usage error and --help come back as exceptions main() turns into JSON."""

    def error(self, message):
        raise _Usage(message, self.format_usage().strip())

    def print_help(self, file=None):
        raise _Help(self.format_help())

    def exit(self, status=0, message=None):
        if status:
            raise _Usage((message or "").strip() or "usage error", self.format_usage().strip())
        raise _Help(self.format_help())


def build_parser():
    ap = DhParser(prog="dh", description="Deckhand control plane — `dh next` tells you what to do.")
    ap.add_argument("--project", help="project folder (default: nearest with .deckhand/ or package.json)")
    common = DhParser(add_help=False)
    common.add_argument("--project", default=argparse.SUPPRESS, help=argparse.SUPPRESS)   # accepted after the subcommand too
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, parents=(), **k: _add(*a, parents=[common, *parents], **k)  # type: ignore[method-assign]

    p = sub.add_parser("init"); p.add_argument("--name", required=True); p.add_argument("--mode", default="phased", choices=STATE.MODES); p.add_argument("--path", default="pool", choices=STATE.PATHS)
    p.add_argument("--for", dest="for_", choices=["me", "client"], help="client: this project keeps its own settings and secrets")
    sub.add_parser("status"); sub.add_parser("next")
    p = sub.add_parser("resume", help="where the project stands, from its files — any AI, any fresh session")
    p.add_argument("--check", action="store_true", help="re-prove every claim against reality"); p.add_argument("--online", action="store_true")
    p.add_argument("--hook", action="store_true", help="SessionStart hook: plain text, nothing outside a deckhand project")
    p.add_argument("--install-hook", choices=["claude"], help="add the SessionStart hook to Claude Code's user settings")
    p = sub.add_parser("hook", help="harness hook entry point (dh harness install wires it): stdin = the harness's hook JSON; raw output, exit 2 = block")
    p.add_argument("event", choices=["pre", "post", "start", "stop"]); p.add_argument("--harness")
    p = sub.add_parser("harness", help="write deckhand's hooks into the agent harness's own config, and prove they block")
    p.add_argument("action", choices=["detect", "install", "doctor", "uninstall"]); p.add_argument("--harness"); p.add_argument("--dry", action="store_true")
    p = sub.add_parser("note", help="decision | doing | next — what would otherwise live only in the chat")
    p.add_argument("kind", choices=RESUME.KINDS); p.add_argument("text", nargs="+")
    p = sub.add_parser("brief"); p.add_argument("action", choices=["show", "set"]); p.add_argument("pairs", nargs="*")
    p = sub.add_parser("phase"); p.add_argument("action", choices=["done", "skip"]); p.add_argument("phase", choices=STATE.PHASE_IDS)
    p.add_argument("--reason"); p.add_argument("--force", nargs="?", const="", help="record done despite a red check; needs a reason (--force \"why\" or --reason), kept and shown")
    p = sub.add_parser("gate"); p.add_argument("action", choices=["pass"]); p.add_argument("gate"); p.add_argument("--note", default="")
    p.add_argument("--quote", help="the owner's own words, verbatim (required in phased mode; a change request re-opens instead)")
    p = sub.add_parser("reopen"); p.add_argument("phase", choices=STATE.PHASE_IDS); p.add_argument("--reason", required=True)

    where = DhParser(add_help=False)
    w = where.add_mutually_exclusive_group()
    w.add_argument("--here", dest="where", action="store_const", const="project", help="this project's own layer (.deckhand/, gitignored)")
    w.add_argument("--machine", dest="where", action="store_const", const="machine", help="~/.deckhand (every project)")
    p = sub.add_parser("profile", parents=[where]); p.add_argument("action", choices=["show", "set", "doctor", "where"]); p.add_argument("pairs", nargs="*"); p.add_argument("--offline", action="store_true")
    p.add_argument("--set", dest="bind_to", metavar="here|machine|FOLDER", help="where: where this project keeps its settings and keys (remembered)")
    p = sub.add_parser("vault", parents=[where]); p.add_argument("action", choices=["set", "list"]); p.add_argument("name", nargs="?")
    p = sub.add_parser("pending", help="what only the owner can do: list · add · done · drop · wait (waiting-confirm) · decide — project PENDING.md or --machine")
    p.add_argument("action", choices=["list", "add", "done", "drop", "wait", "decide"]); p.add_argument("text", nargs="*", help="add/decide: what · done/drop/wait: the ID")
    for f in ("--why", "--how", "--where", "--when", "--rec", "--reason"):
        p.add_argument(f, default="")
    p.add_argument("--for-project", dest="for_project", help="machine item that powers one project")
    p.add_argument("--machine", action="store_true", help="~/.deckhand/pending.md: the owner's own cross-project items")
    p.add_argument("--all", action="store_true", help="list: include deferred (when:) and nag: no items")

    p = sub.add_parser("pool"); p.add_argument("action", choices=["query", "show", "vet", "add", "list", "sync"]); p.add_argument("target", nargs="?")
    p.add_argument("--shape"); p.add_argument("--features"); p.add_argument("--languages"); p.add_argument("--top", type=int, default=3); p.add_argument("--mine", action="store_true"); p.add_argument("--lane", default="web")

    p = sub.add_parser("plan"); p.add_argument("action", choices=["init", "lint", "render", "split"]); p.add_argument("--agents", type=int, default=3); p.add_argument("--force", action="store_true")
    p.add_argument("--from-app", action="store_true", help="path=existing: start the sitemap from the routes the app already serves")
    p = sub.add_parser("bb", help="shared memory for parallel agents: post · read · flag NAME · wait NAME --max S")
    p.add_argument("action", choices=["post", "read", "flag", "wait"]); p.add_argument("name", nargs="?"); p.add_argument("--wp", default="all"); p.add_argument("--kind", default="note")
    p.add_argument("--msg"); p.add_argument("--last", type=int, default=40); p.add_argument("--max", type=int, default=170)

    p = sub.add_parser("clone"); p.add_argument("template"); p.add_argument("--to", required=True); p.add_argument("--no-install", action="store_true")
    p = sub.add_parser("adopt"); p.add_argument("source"); p.add_argument("--to"); p.add_argument("--install", action="store_true")
    p = sub.add_parser("scaffold"); p.add_argument("--to", required=True); p.add_argument("--pm", default="npm", choices=["npm", "pnpm", "bun", "yarn"])
    p = sub.add_parser("compose"); p.add_argument("--page", default="app/page.tsx"); p.add_argument("--sections", default="navbar,hero,features,pricing,faq,cta,footer"); p.add_argument("--copy")
    p = sub.add_parser("dev", help="start|stop|status the app and the services it needs · add|remove NAME a service (database, queue…)")
    p.add_argument("action", choices=["start", "stop", "status", "add", "remove", "port"]); p.add_argument("name", nargs="?"); p.add_argument("--port", type=int)
    p.add_argument("--from", dest="from_port", type=int, default=3000, help="port: the first port to try")
    p.add_argument("--cmd", dest="svc_cmd", help="add: the command that starts the service")   # dest: `cmd` is the subcommand
    p.add_argument("--ready", help="add: regex of the log line that says it is up")
    p.add_argument("--env-file", help="add: KEY=VALUE file loaded into the service's environment (e.g. .env)")
    p = sub.add_parser("suggest", help="what the owner could do next, by importance (optional) · dismiss ID [--days N]")
    p.add_argument("action", nargs="?", choices=["list", "dismiss"], default="list"); p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true", help="every suggestion, dismissed ones included"); p.add_argument("--days", type=int, default=7, help="dismiss for 1..365 days")
    p = sub.add_parser("workflow", help="proven paths: query (top 3) · use · next steps · todo · step · show · list · lint · new --from-run · save · publish · sync")
    p.add_argument("action", choices=["query", "use", "show", "todo", "step", "list", "lint", "new", "save", "publish", "sync", "status"])
    p.add_argument("target", nargs="?", help="a workflow ref (id, id@v, mine:|base:|community:id, or a .json file) · a step id for `step`")
    p.add_argument("state", nargs="?", choices=["done", "skip"], help="step: done | skip")
    for f in ("--deliverable", "--industry", "--shape", "--features", "--harness", "--os", "--why", "--id", "--title", "--phase"):
        p.add_argument(f)
    p.add_argument("--min-level", choices=["draft", "proven", "trusted"]); p.add_argument("--top", type=int, default=3)
    p.add_argument("--refresh", action="store_true"); p.add_argument("--accept", action="store_true", help="use: the owner saw the non-dh commands and said OK")
    p.add_argument("--set", action="append", default=[], help="use: a param, name=value (repeatable)")
    p.add_argument("--format", choices=["json", "md"], default="json"); p.add_argument("--from-run", action="store_true")
    p.add_argument("--from-autopsy", help="save: the workflow autopsy id whose proposals to apply"); p.add_argument("--proposals", default="", help="save: P1,P3 (the ones the owner accepted)")
    p.add_argument("--public", action="store_true", help="save: a bundle for the community pool (a PR), not your own pool")
    p = sub.add_parser("base", help="record the base of a project built another way (by hand, another tool)")
    p.add_argument("action", choices=["record", "show"]); p.add_argument("--kind", choices=["scratch", "existing", "template"], default="scratch")
    p.add_argument("--note", default=""); p.add_argument("--source")

    p = sub.add_parser("rebrand"); p.add_argument("action", choices=["scan", "apply", "check"]); p.add_argument("pairs", nargs="*"); p.add_argument("--dry", action="store_true"); p.add_argument("--allow", default="")
    p = sub.add_parser("slop", help="AI-sounding copy, found by script: check [PATH…|--text T|--url U] · brief · langs · lint · add · allow · export")
    p.add_argument("action", choices=["check", "brief", "langs", "lint", "add", "allow", "export"]); p.add_argument("target", nargs="*")
    p.add_argument("--text", help="the text itself, or - for stdin"); p.add_argument("--url", help="read the rendered pages of any site")
    p.add_argument("--lang", help="en, fr, es… (default: brief.languages, else detected per text)")
    p.add_argument("--buzz", action="store_true", help="add: a weaker word (use sparingly), not a strong tell")
    p.add_argument("--phrase", action="store_true"); p.add_argument("--fix", default="", help="add: the plainer word to use instead")
    p = sub.add_parser("swap"); p.add_argument("action", choices=["scan", "check"])
    p = sub.add_parser("verify"); p.add_argument("--url"); p.add_argument("--skip", default=""); p.add_argument("--allow", default=""); p.add_argument("--reason", default="", help="why rows are skipped (recorded; without it a skipped blocking row keeps the report red)")

    p = sub.add_parser("deploy"); p.add_argument("action", choices=["target", "ship", "smoke", "raw"]); p.add_argument("rest", nargs=argparse.REMAINDER)
    p.add_argument("--app"); p.add_argument("--url"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("ops"); p.add_argument("action", choices=["suggest", "add", "list"]); p.add_argument("bot", nargs="?"); p.add_argument("--runner", default=None, help="github | cron | local | hermes (default: hermes inside a Hermes session, else github)")

    p = sub.add_parser("learn"); p.add_argument("action", choices=["add", "match", "preflight", "promote", "from-failure", "list"])
    p.add_argument("--phase", default="build"); p.add_argument("--symptom"); p.add_argument("--cause", default=""); p.add_argument("--fix", default="")
    p.add_argument("--signature"); p.add_argument("--command"); p.add_argument("--rung", default="pitfall"); p.add_argument("--scope", default="global")
    p.add_argument("--log"); p.add_argument("--text"); p.add_argument("--stack", default="")
    p = sub.add_parser("run"); p.add_argument("--phase"); p.add_argument("--fix", action="store_true", help="replay a proven auto-safe recipe, retry once")
    p.add_argument("argv", nargs=argparse.REMAINDER)
    p = sub.add_parser("autopsy", help="deterministic session analysis: failures -> recipes, lessons, skill proposals, playbooks")
    p.add_argument("source", nargs="?", help="a Claude Code transcript .jsonl or a run log (default: .deckhand/runs.jsonl, else the latest transcript)")
    p.add_argument("--latest", action="store_true"); p.add_argument("--apply", action="store_true")
    p.add_argument("--session", help="a Hermes session id (state.db); default: HERMES_SESSION_ID, else the latest in this project")
    p.add_argument("--workflow", action="store_true", help="the workflow autopsy: timeline, questions asked + answers, deviations, cost, proposals")
    p.add_argument("--part", help="with --workflow: only one section (timeline|questions|deviations|errors|delegation|guidance|proposals)")

    p = sub.add_parser("harvest"); p.add_argument("--name", required=True); p.add_argument("--to"); p.add_argument("--repo"); p.add_argument("--public", action="store_true")
    p.add_argument("--push", action="store_true", help="secret scan, then a private repo on your GitHub + your library index")
    p = sub.add_parser("research", help="evidence: brief · add/seen (shared sources) · merge · verify (quotes re-checked) · score (cost of a run)")
    p.add_argument("action", choices=["brief", "add", "seen", "merge", "verify", "score"]); p.add_argument("target", nargs="?")
    p.add_argument("--focus"); p.add_argument("--agent"); p.add_argument("--by"); p.add_argument("--kind", default=""); p.add_argument("--note", default="")
    p.add_argument("--refresh", action="store_true"); p.add_argument("--offline", action="store_true")
    p.add_argument("--baseline"); p.add_argument("--research"); p.add_argument("--baseline-research")
    p = sub.add_parser("seo", help="be found on Google and in AI answers: audit · apply (add/improve, never overwrite) · undo · ping · facts")
    p.add_argument("action", choices=["audit", "apply", "undo", "ping", "facts"]); p.add_argument("--url")
    p.add_argument("--force", action="store_true", help="undo: even over files edited since the apply")
    sub.add_parser("handoff")
    p = sub.add_parser("clean", help="leave no trace: remove Deckhand's own leftover temp folders, browser profiles and stranded siblings (dry run unless --apply)")
    p.add_argument("--apply", action="store_true"); p.add_argument("--older-than", type=float, default=None, metavar="HOURS", help="never touch anything younger (default 2)")
    p.add_argument("--caches", action="store_true", help="also report npm/pnpm caches; with --apply run `npm cache verify`")
    p = sub.add_parser("tryon", help="passthrough to the try-on engine (node)"); p.add_argument("rest", nargs=argparse.REMAINDER)
    return ap


def _deploy_opts(a) -> None:
    """`deploy target --app X --url U --project D`: the REMAINDER swallowed everything after the action; take the options
    back (--project too, so both orders work). Runs before the root is resolved."""
    if a.cmd != "deploy" or a.action == "raw" or not a.rest or getattr(a, "_deploy_done", False):
        return
    dp = DhParser(prog=f"dh deploy {a.action}", add_help=False)
    dp.add_argument("--app"); dp.add_argument("--url"); dp.add_argument("--force", action="store_true"); dp.add_argument("--project")
    try:
        more, left = dp.parse_known_args(a.rest)
    except _Usage as e:
        raise DhError("USAGE", f"dh deploy {a.action}: {e.message}")
    if left:
        raise DhError("USAGE", f"dh deploy {a.action}: unexpected {' '.join(left)}")
    a.app, a.url, a.force = more.app or a.app, more.url or a.url, more.force or a.force
    if more.project:
        a.project = more.project
    a._deploy_done = True


# commands that create their own folder (`--to`) or the project itself; every other command needs an existing folder
CREATES_FOLDER = ("init",)


def _check_root(a) -> Path:
    """One validation of --project for every command: a file is BAD_PROJECT, a folder that does not exist is BAD_PROJECT
    (a typo must not become a stray project) except for `init`, which creates it."""
    given = getattr(a, "project", None)
    root = _root(a)
    if given:
        if root.exists() and not root.is_dir():
            raise DhError("BAD_PROJECT", f"--project {given} is a file, not a folder")
        if not root.exists() and a.cmd not in CREATES_FOLDER:
            raise DhError("BAD_PROJECT", f"--project {given} does not exist (a typo would create a stray project) — "
                          f"to start a project there: {DH} init --name \"<business>\" --project \"{root}\"", init=f"{DH} init --name \"<business>\" --project \"{root}\"")
    return root


def _needs_run(a) -> bool:
    """The commands that change a project's state or files only make sense inside one (a .deckhand/run.json). Everything
    else is read-only, global (profile, vault, learn, pool, clean, workflow list/query/lint…) or creates a project
    itself (init, scaffold, clone, adopt, harvest)."""
    c, act = a.cmd, getattr(a, "action", None)
    if c in ("phase", "gate", "reopen", "note", "plan", "compose", "verify", "handoff", "rebrand", "swap", "seo", "research"):
        return True
    return ((c == "brief" and act == "set") or (c == "pending" and act != "list" and not a.machine) or (c == "bb" and act != "read")
            or (c == "dev" and act in ("start", "stop", "add", "remove")) or (c == "deploy" and act in ("target", "ship", "smoke"))
            or (c == "ops" and act == "add") or (c == "slop" and act == "allow") or (c == "base" and act == "record")
            or (c == "workflow" and act in ("use", "step", "new")) or (c == "suggest" and act == "dismiss"))


def _need_run(root: Path) -> None:
    if not STATE.load(root, required=False):          # RUN_CORRUPT raises from load
        line = f'{DH} init --name "<business>" --project "{root}"'
        raise DhError("NO_RUN", f"no project in {root} (no .deckhand/run.json): nothing was written — start one with `{line}`", init=line)


def dispatch(a):
    root = _root(a)
    c = a.cmd
    if c == "init":
        return STATE.init(root, a.name, a.mode, a.path, for_=a.for_)
    if c == "resume":
        if a.install_hook:
            return RESUME.install_hook()
        if a.check:
            r = RESUME.check(root, online=a.online)
            if not r["ok"]:
                raise DhError("DRIFT", f"{r['drift']} claim(s) no longer true — see claims; fix or tell the owner", **r)
            return r
        return RESUME.resume(root)
    if c == "note":
        return RESUME.note(root, a.kind, " ".join(a.text))
    if c == "status":
        s = STATE.load(root)
        return {**STATE.summary(root, s), "phases": {k: v["status"] for k, v in s["phases"].items()}, "gates": {k: v["status"] for k, v in s["gates"].items()}, "base": s.get("base")}
    if c == "next":
        from . import guide
        return guide.next_step(root)
    if c == "brief":
        return cmd_brief(a)
    if c == "phase":
        if a.action == "skip":
            return STATE.phase_skip(root, a.phase, a.reason or "")
        r = STATE.phase_done(root, a.phase, force_reason=None if a.force is None else (a.force.strip() or (a.reason or "").strip()))
        if not r["ok"]:
            raise DhError("CHECK_FAILED", f"phase {a.phase} is not done yet", check=r["check"])
        if a.phase == "define":                          # launch needs from the owner: asked now, not at deploy (audit F6)
            from . import pending as PEND
            r["launch"] = PEND.launch_readiness(root)
        return r
    if c == "gate":
        s = STATE.load(root)
        if STATE.owner_gate(s, a.gate) and not a.quote:
            raise DhError("NEED_QUOTE", f"a gate passes on the owner's own words: dh gate pass {a.gate} --quote \"<their message, verbatim>\"",
                          why="an agent once passed G1 on its own paraphrase of a change request")
        return STATE.gate_pass(root, a.gate, a.note, quote=a.quote)
    if c == "reopen":
        return STATE.reopen(root, a.phase, a.reason)
    if c == "profile":
        from . import profile as PR
        if a.action == "set":
            return PR.set_fields(a.pairs, where=a.where)
        if a.action == "where":
            if a.pairs:
                raise DhError("USAGE", "dh profile where [--set here | machine | <folder outside the project>]")
            return PR.bind(a.bind_to) if a.bind_to is not None else PR.where_view()
        if a.action == "doctor":
            from . import pending as PEND
            md = PEND.profile_md()
            return {**PR.doctor(online=not a.offline), **({"notes_md": md} if md else {})}
        pp = PR.project_profile_path()
        from . import pending as PEND
        md = PEND.profile_md()
        return {"profile": PR.load(), "scope": PR.scope(), "path": str(PR.profile_path()),
                "project_layer": str(pp) if pp and pp.exists() else None, "where": PR.where_brief(), **({"notes_md": md} if md else {})}
    if c == "vault":
        from . import profile as PR
        if a.action == "list":
            pv = PR.project_vault_path()
            return {"names": sorted(PR.vault_read()), "by_layer": PR.vault_names(), "scope": PR.scope(), "path": str(PR.vault_path()),
                    "project_layer": str(pv) if pv and pv.exists() else None, "where": PR.where_brief(),
                    **({"shell": PR.shell_line()} if PR.shell_line() else {})}
        if not a.name:
            raise DhError("USAGE", "dh vault set NAME [--here|--machine]   (value on stdin or prompted — never on the command line)")
        return PR.vault_set(a.name, where=a.where)
    if c == "pending":
        from . import pending as PEND
        text = " ".join(a.text).strip()
        if a.action == "list":
            return PEND.summary(root, include_deferred=a.all)
        if a.action in ("add", "decide"):
            return PEND.add(root, text, a.why, a.how, a.where, machine=a.machine, when=a.when or None, project=a.for_project,
                            decide=a.action == "decide", rec=a.rec or None)
        if not text:
            raise DhError("USAGE", f"dh pending {a.action} P-0NN")
        if a.action == "wait":
            return PEND.set_status(root, text, "waiting-confirm", machine=a.machine)
        if a.action == "drop" and not a.reason:
            raise DhError("NEED_REASON", "a dropped item keeps its reason: --reason \"…\"")
        return PEND.close(root, text, machine=a.machine, drop_reason=a.reason if a.action == "drop" else None)
    if c == "pool":
        from . import pool as POOL
        if a.action == "query":
            brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
            if a.shape: brief["shape"] = a.shape
            if a.features: brief["features"] = [x.strip() for x in a.features.split(",")]
            if a.languages: brief["languages"] = [x.strip() for x in a.languages.split(",")]
            brief["lane"] = a.lane
            return POOL.query(brief, a.top, source="mine" if a.mine else None)
        if a.action == "show":
            return POOL.show(a.target)
        if a.action == "sync":
            from . import harvest as H
            return H.library_sync()
        if a.action in ("vet", "add") and not a.target:
            raise DhError("USAGE", f"dh pool {a.action} owner/repo")
        if a.action == "vet":
            return POOL.vet(a.target, mine=a.mine)
        if a.action == "add":
            if Path(a.target).expanduser().is_dir():                    # the owner's own project folder: measured on disk
                if not a.mine:
                    raise DhError("USAGE", f"{a.target} is a local folder: `dh pool add {a.target} --mine` (your own projects only)")
                row = POOL.measure_local(Path(a.target).expanduser())
                if a.shape:
                    row["shape"] = a.shape
                if a.features:
                    row["features"] = sorted(set(row["features"]) | {x.strip() for x in a.features.split(",") if x.strip()})
                return {**POOL.add_local(Path(a.target), row), "row": row}
            return POOL.add(a.target, mine=a.mine, shape=a.shape, features=[x.strip() for x in (a.features or "").split(",") if x.strip()])
        return {"templates": [{k: r.get(k) for k in ("name", "source", "shape", "lane", "license", "stars", "path")} for r in POOL.rows()
                              if not a.mine or r.get("source") == "mine"]}
    if c == "plan":
        from . import plan as PL
        if a.action == "init":
            return PL.init(root, a.force, from_app=a.from_app)
        if a.action == "lint":
            r = PL.lint(root)
            if not r["ok"]:
                raise DhError("PLAN_ERRORS", f"{len(r['errors'])} errors in the plan", **r)
            return r
        if a.action == "render":
            return PL.render(root)
        return PL.split(root, a.agents)
    if c == "bb":
        from . import plan as PL
        if a.action in ("flag", "wait"):
            if not a.name:
                raise DhError("USAGE", f"dh bb {a.action} NAME" + (" --max SECONDS" if a.action == "wait" else ""))
            return PL.bb_flag(root, a.name, a.msg or "") if a.action == "flag" else PL.bb_wait(root, a.name, a.max)
        if a.action == "post":
            if not a.msg:
                raise DhError("USAGE", "--msg required")
            return PL.bb_post(root, a.wp, a.kind, a.msg)
        return {"entries": PL.bb_read(root, None if a.wp == "all" else a.wp, None if a.kind == "note" else a.kind, a.last)}
    if c in ("clone", "adopt", "scaffold"):
        from . import build as B, profile as PR
        if c != "adopt":                                 # adopt is a read-only analysis, allowed at define
            STATE.require(root, "build")                 # no clone before G1
        who = PR.scope()                                 # the planning folder's: for me, or for a client
        to = (root / a.to) if a.to else None             # a relative --to is the project's, never the shell's cwd
        if c == "clone":
            out = B.clone(a.template, to, do_install=not a.no_install)
        elif c == "adopt":
            out = B.adopt(a.source, to, do_install=a.install)
        else:
            out = B.scaffold(to, a.pm)
        if not B.planning_folder(root):                  # run from inside another business: nothing of it comes along
            return out
        if who == "client":                              # the app folder keeps the client's own layer too
            PR.set_scope(out["project"], "client")
        carried = PR.carry(root, out["project"])         # … and the same settings/keys choice (`dh profile where`)
        moved = B.carry_run(root, out["project"])        # … and the run itself, when the app lives in another folder
        return {**out, **({"carried": carried} if carried else {}), **({"run_moved": moved, "next": f"cd {moved['to']} — the project continues there"} if moved else {})}
    if c in ("compose", "dev"):
        from . import build as B
        if c == "compose":
            return B.compose(root, a.page, [s.strip() for s in a.sections.split(",")], a.copy)
        if a.action == "port":
            from .util import free_port, reserved_ports
            return {"port": free_port(a.from_port), "reserved": reserved_ports(), "why": "bind-tested; Windows reserved ranges skipped"}
        if a.action == "add":
            return B.service_add(root, a.name, a.svc_cmd, a.port, a.ready, a.env_file)
        if a.action == "remove":
            if not a.name:
                raise DhError("USAGE", "dh dev remove NAME")
            return B.service_remove(root, a.name)
        return {"start": lambda: B.dev_start(root, a.port), "stop": lambda: B.dev_stop(root), "status": lambda: B.dev_status(root)}[a.action]()
    if c == "suggest":
        from . import suggest as SUG
        if a.action == "dismiss":
            if not a.id:
                raise DhError("USAGE", "dh suggest dismiss ID [--days N]")
            return SUG.dismiss(root, a.id, a.days)
        r = SUG.compute(root, limit=0 if a.all else 10, include_dismissed=a.all)
        return {**r, "lines": SUG.lines(r)}
    if c == "workflow":
        return cmd_workflow(a, root)
    if c == "base":
        from . import build as B
        if a.action == "show":
            return {"base": (STATE.load(root)).get("base")}
        return B.record_base(root, a.kind, a.note, a.source)
    if c == "rebrand":
        from . import brand as BR
        if a.action == "scan":
            return BR.scan(root)
        if a.action == "apply":
            if not a.dry:
                STATE.require(root, "build")             # after G1: his brand goes on at the end of build, before G2 (audit F3)
            brand = {k.replace("brand.", ""): v for k, v in _kv(a.pairs).items()}
            return BR.apply(root, brand, dry=a.dry)
        r = BR.check(root, allow=tuple(x for x in a.allow.split(",") if x))
        if not r["ok"]:
            raise DhError("LEAKS", f"{r['blocking']} blocking findings", **r)
        return r
    if c == "slop":
        return cmd_slop(a, root)
    if c == "swap":
        from . import swap as SW
        if a.action == "scan":
            return SW.scan(root)
        r = SW.check(root)
        if not r["ok"]:
            raise DhError("SWAP_INCOMPLETE", "a vendor SDK is still in the code", **r)
        return r
    if c == "verify":
        from . import verify as V
        r = V.run_verify(root, a.url, skip=tuple(x for x in a.skip.split(",") if x), allow=tuple(x for x in a.allow.split(",") if x), skip_reason=a.reason)
        if not r["ok"]:
            raise DhError("VERIFY_FAILED", "blocking rows are red (see .deckhand/VERIFY.md)", **r)
        return r
    if c == "deploy":
        from . import deploy as D
        if a.action != "raw" and a.rest:                # REMAINDER swallowed the options written after the action
            _deploy_opts(a)
        if a.action == "target":
            return D.target(root, a.app, a.url)
        if a.action == "ship":
            STATE.require(root, "deploy")                # no deploy before G4
            return D.ship(root, force=a.force)
        if a.action == "smoke":
            sm = D.smoke(root, a.url)
            if not sm["ok"]:
                raise DhError("SMOKE_FAILED", sm["evidence"], smoke=sm)
            return sm
        if a.rest[:1] == ["deploy"]:
            STATE.require(root, "deploy")                # `raw deploy` ships a release too: same gates as ship
        return {"exit": D.passthrough(a.rest)}
    if c == "ops":
        from . import ops as O
        if a.action == "suggest":
            return O.suggest(root)
        if a.action == "list":
            return {"bots": O.catalog()}
        if not a.bot:
            raise DhError("USAGE", "dh ops add <bot-id> [--runner github|cron|local|hermes]")
        from . import workflow as WF
        return O.add(root, a.bot, a.runner or ("hermes" if WF.harness() == "hermes" and os.environ.get("HERMES_HOME") else "github"))
    if c == "learn":
        from . import learn as LE
        r_ = root if (root / ".deckhand").exists() else None
        if a.action == "add":
            if not a.symptom or not a.fix:
                raise DhError("USAGE", "--symptom and --fix are required")
            return LE.add(r_, a.phase, a.symptom, a.cause, a.fix, a.signature, a.command, a.rung, a.scope, [x for x in a.stack.split(",") if x])
        if a.action == "match":
            text = Path(a.log).read_text(encoding="utf-8", errors="replace") if a.log else (a.text or sys.stdin.read())
            return {"known_fixes": LE.match(r_, text)}
        if a.action == "preflight":
            return {"phase": a.phase, "lessons": LE.preflight(r_, a.phase)}
        if a.action == "promote":
            return LE.promote(r_)
        if a.action == "from-failure":
            return LE.from_failure(root, a.fix, a.cause, a.rung, a.scope, a.command)
        return {"lessons": LE.all_lessons(r_)}
    if c == "run":
        from . import learn as LE
        argv = a.argv[1:] if a.argv and a.argv[0] == "--" else a.argv
        r = LE.run_cmd(root, argv, a.phase, fix=a.fix)
        if not r["ok"]:
            raise DhError("COMMAND_FAILED", f"exit {r['code']}", exit=r["code"], **{k: v for k, v in r.items() if k not in ("code", "ok")})
        return r
    if c == "autopsy":
        if a.workflow:
            from . import wfautopsy as WA
            return WA.run(root, a.source, latest=a.latest, part=a.part, session=a.session)
        from . import autopsy as AU
        return AU.autopsy(root, a.source, latest=a.latest, apply=a.apply, session=a.session)
    if c == "harvest":
        from . import harvest as H
        return H.harvest(root, a.name, Path(a.to) if a.to else None, a.repo, private=not a.public, push=a.push)
    if c == "research":
        from . import research as RS
        if a.action == "brief":
            if not a.focus or not a.agent:
                raise DhError("USAGE", "dh research brief --focus " + "|".join(RS.POLICY["focus"]) + " --agent ID")
            return RS.brief(root, a.focus, a.agent)
        if a.action == "add":
            if not a.target:
                raise DhError("USAGE", "dh research add URL --by ID --kind K --note \"dense facts\"")
            return RS.add_source(root, a.target, a.by or "", a.kind, a.note)
        if a.action == "seen":
            return RS.seen(root, a.target)
        if a.action == "merge":
            return RS.merge(root)
        if a.action == "score":
            return RS.score(root, a.target, a.baseline, a.research, a.baseline_research)
        r = RS.verify(root, refresh=a.refresh, offline=a.offline)
        if not r["ok"]:
            raise DhError("RESEARCH_UNVERIFIED", f"{r['summary']['mismatch']} quotes not on their page, {r['summary']['invalid']} invalid claims, "
                          f"{r['summary']['terms_bad']} bad terms — fix or relabel (references/research-card.md)", **r)
        return r
    if c == "clean":
        from . import clean as CLEAN
        return CLEAN.clean(project=root, apply=a.apply, older_than=a.older_than, caches=a.caches)
    if c == "seo":
        from . import seo as SEO
        if a.action == "apply":
            return SEO.apply(root)
        if a.action == "undo":
            return SEO.undo(root, force=a.force)
        if a.action == "ping":
            return SEO.ping(root)
        if a.action == "facts":
            return {"owner": SEO.owner_gaps(SEO.ctx_of(root))}
        r = SEO.audit(root, a.url)
        sev = {s: len([x for x in r["findings"] if x["severity"] == s]) for s in ("block", "high", "medium", "low")}
        nxt = ("fix the launch-breakers first; " if r["blockers"] else "") + (
            ("`dh seo apply` fixes " + ", ".join(r["auto_fixable"]) + " — " if r["auto_fixable"] else "")
            + ("run it now (this path gets SEO by default)" if r["policy"] == "apply" else "DECISION NEEDED — recommend it to the owner before going live"))
        return {"score": r["score"], "rendered": r["rendered"], "by_severity": sev,
                "blockers": [{k: x[k] for k in ("rule", "title", "detail", "where")} for x in r["blockers"]],
                "top": [{k: x[k] for k in ("rule", "severity", "title", "detail", "where", "auto")} for x in r["findings"][:12]],
                "owner_open": [o["label"] for o in r["owner"]], "report": ".deckhand/SEO.md", "pending": "PENDING.md (Detected by dh seo)",
                "next": nxt if (r["auto_fixable"] or r["blockers"]) else "write/refine per-page titles and descriptions (copy.json → seo.pages); owner items are in PENDING.md"}
    if c == "harness":
        from . import harness as HA
        from .workflow import harness as detected
        if a.action == "detect":
            return HA.detect()
        h = a.harness or detected()
        if h == "unknown":
            raise DhError("USAGE", "which harness? dh harness " + a.action + " --harness claude-code|codex|gemini-cli|cursor|hermes|opencode")
        if a.action == "install":
            return HA.install(h, dry=a.dry)
        if a.action == "uninstall":
            return HA.uninstall(h)
        r = HA.doctor(h)
        if not r["ok"]:
            raise DhError("HOOKS_OFF", f"{h}: deckhand's hooks are not all working", **r)
        return r
    if c == "handoff":
        from . import handoff as HO
        return HO.write(root)
    if c == "tryon":
        node = shutil.which("node")
        if not node:
            raise DhError("NO_NODE", "try-on needs Node.js 18+")
        return {"exit": subprocess.call([node, str(TRYON / "cli.mjs"), *tryon_argv(a.rest, root)])}
    raise DhError("USAGE", c)


def _log(a, shown: str, code: int, out: str = "") -> None:
    """Every dh call lands in .deckhand/runs.jsonl (phase transitions make the playbooks `dh autopsy` learns)."""
    if a.cmd in ("run", "autopsy", "next", "status", "resume", "note", "suggest"):
        return                                           # `run` logs itself; read-only calls are noise; notes have their own file
    try:
        from . import learn as LE
        LE.log_run(_root(a), shown, code, out)
    except Exception:  # noqa: BLE001 — logging never breaks a command
        pass


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")        # Windows consoles default to cp1252
    except Exception:
        pass
    ap = build_parser()
    try:
        a = ap.parse_args(argv)
    except _Usage as e:
        return emit({"ok": False, "code": "USAGE", "message": e.message, "usage": e.usage}, 2)
    except _Help as h:
        return emit({"ok": True, "help": h.text})
    if a.cmd == "resume" and a.hook:                     # the one non-JSON output: a harness injects it as context
        sys.stdout.write(RESUME.hook(RESUME.stdin_if_piped(), start=Path(a.project) if getattr(a, "project", None) else None))
        return 0
    if a.cmd == "hook":                                  # raw output for the harness, like resume --hook; not logged (runs per tool call)
        from . import hooks as HOOKS
        code, out, err = HOOKS.handle(a.event, RESUME.stdin_if_piped(), a.harness)
        if out:
            sys.stdout.write(out)
        if err:
            sys.stderr.write(err)
        return code
    shown = "dh " + " ".join(argv if argv is not None else sys.argv[1:])
    root = None
    out = None
    try:
        _deploy_opts(a)
        root = _check_root(a)
        from . import profile as PROFILE
        PROFILE.use_project(root)                        # the project's own profile/vault layer applies to this command
        if _needs_run(a):
            _need_run(root)
        out = dispatch(a)
        if a.cmd == "tryon":
            _log(a, shown, out.get("exit", 0))
            return out.get("exit", 0)
        _log(a, shown, 0)
        _observe(a, root, shown)
        res = {"ok": True, **out} if isinstance(out, dict) else {"ok": True, "result": out}
        if SKIPPED["lines"]:                             # a corrupt log line was skipped, not fatal: say how many
            res["skipped_lines"] = SKIPPED["lines"]
        return emit(runnable_obj(res))
    except DhError as e:
        _log(a, shown, 1, f"{e.code}: {e.message}")
        return emit(runnable_obj({**e.extra, "ok": False, "code": e.code, "message": e.message}), 1)   # extra never overrides the verdict
    except KeyboardInterrupt:
        return emit({"ok": False, "code": "INTERRUPTED"}, 130)
    except Exception as e:                              # a hand-edited file of the wrong shape: JSON, never a traceback
        _log(a, shown, 1, f"INTERNAL: {type(e).__name__}: {e}")
        return emit({"ok": False, "code": "INTERNAL", "message": f"{type(e).__name__}: {e}",
                     "hint": "a .deckhand/*.json file may have the wrong shape; `dh resume --check`, then fix or restore it"}, 1)
    finally:
        if root is not None:
            _refresh(a, root, out)


def _observe(a, root: Path, shown: str) -> None:
    """A pinned workflow ticks the step this command completes (or records a deviation)."""
    if a.cmd in ("next", "status", "resume", "note", "workflow", "autopsy", "suggest"):
        return
    from . import workflow as WF
    WF.observe(root, shown, 0)


def _refresh(a, root: Path, out) -> None:
    """RESUME.md follows every command, success or failure — a new session always starts from the current truth."""
    if a.cmd in ("resume", "note"):
        return                                           # they write it themselves
    roots = {root}
    if a.cmd in ("clone", "adopt", "scaffold") and isinstance(out, dict) and out.get("project"):
        roots.add(Path(out["project"]))
    for r in roots:
        try:
            RESUME.write(r)
        except Exception:  # noqa: BLE001 — the summary never breaks a command
            pass
