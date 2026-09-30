#!/usr/bin/env python3
"""gen_cli_flags.py — writes skills/deckhand/references/cli-flags.md (command -> flags, with the argparse help text)
from the real `dh` parser (dhlib.cli.build_parser). `--check` exits 1 when the committed file is stale.
Stdlib only."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "deckhand"
OUT = SKILL / "references" / "cli-flags.md"
SKIP = {"-h", "--help", "--project"}


# Flags the parser declares without help text: a one-line meaning taken from how dhlib/cli.py uses them.
# "command --flag" wins over "--flag".
NOTES = {
    "--name": "name of the project / library entry", "--mode": "phased (the run stops at the gates) or auto", "--path": "how the base is chosen",
    "--online": "also probe the network", "--offline": "no network probes", "--set": "profile: where settings live (here, machine or a folder); workflow use: name=value",
    "--reason": "why (recorded with the change)", "--why": "why: what it unblocks (pending add) · why a step was done or skipped (workflow step)",
    "--how": "exact steps for the owner", "--where": "where the owner does it", "--when": "defer until a phase/gate trigger",
    "--rec": "your recommendation for the decision", "--shape": "site shape to match", "--features": "comma-separated features to match",
    "--languages": "comma-separated site languages to match", "--top": "how many results to return", "--mine": "the owner's own library instead of the shared pool",
    "--lane": "pool lane to match (default web); a base of another lane is refused", "--agents": "how many parallel work packages to split the plan into",
    "--force": "override the guard", "--wp": "work package id (default all)", "--kind": "entry kind (bb) · source kind (research)", "--msg": "the message text",
    "--last": "how many latest entries to read (default 40)", "--max": "seconds to wait (default 170)", "--to": "destination folder",
    "--no-install": "skip the dependency install", "--install": "run the dependency install", "--pm": "package manager for the scaffold (default npm)",
    "--page": "page file to compose (default app/page.tsx)", "--sections": "comma-separated sections (default navbar,hero,features,pricing,faq,cta,footer)",
    "--copy": "copy.json holding the page's words", "--port": "dev-server port", "--days": "snooze length in days", "--deliverable": "brief.deliverable to match",
    "--industry": "industry to match", "--harness": "harness to match", "--os": "operating system to match", "--id": "workflow id", "--title": "workflow title",
    "--phase": "phase the entry belongs to", "--refresh": "re-read the source instead of the cache", "--from-run": "extract the workflow from this run",
    "--note": "free-text note", "--source": "where the base came from", "--dry": "show what would change, write nothing", "--allow": "comma-separated names to allow",
    "--url": "check this site (live or running) instead of the local build", "--skip": "comma-separated check rows NOT to run",
    "--app": "Coolify application UUID", "--symptom": "what went wrong, as seen", "--cause": "the root cause", "--fix": "the proven fix",
    "--signature": "regex that recognizes the error (default: the symptom, escaped)", "--command": "the command the lesson applies to",
    "--rung": "rung of the lesson (default pitfall; evidence only moves it up)", "--scope": "global (~/.deckhand, default) or project (.deckhand/lessons.jsonl)",
    "--log": "path of a log file to read", "--text": "the text / error text itself", "--stack": "comma-separated stacks the lesson applies to",
    "--latest": "read the latest session", "--apply": "write the result (default: dry run)", "--repo": "owner/name of the target repo", "--public": "public, not private",
    "--focus": "research focus", "--agent": "agent the brief is for", "--by": "who found the source", "--baseline": "baseline to score against",
    "--research": "research run to score", "--baseline-research": "research run of the baseline", "--lang": "language code", "--from": "first port to try",
    "--here": "this project's layer", "--machine": "the machine layer (~/.deckhand)", "--check": "prove only, write nothing", "--hook": "hook mode", "--all": "include everything",
    "--buzz": "add: a weaker word (use sparingly), not a strong tell", "--phrase": "add: a multi-word phrase, not a single word",
}


def meaning(cmd: str, flag: str, help_: str) -> str:
    return help_ or NOTES.get(f"{cmd} {flag}") or NOTES.get(flag) or "—"


def commands() -> list:
    """[(command, [(flag-with-argument, help)])] for every `dh` subcommand that has options."""
    sys.path.insert(0, str(SKILL))
    from dhlib.cli import build_parser
    subs = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    rows = []
    for name, sp in subs.choices.items():
        fl = []
        for a in sp._actions:
            if not a.option_strings or set(a.option_strings) & SKIP:
                continue
            arg = "" if a.nargs == 0 else f" {(a.metavar or a.dest.upper())}"
            if a.choices and a.nargs != 0:
                arg = " {" + "|".join(map(str, a.choices)) + "}"
            help_ = " ".join((a.help or "").split()).replace("|", "\\|")
            fl.append(("/".join(a.option_strings) + arg, meaning(name, a.option_strings[-1], help_)))
        if fl:
            rows.append((name, fl))
    return rows


def table() -> str:
    out = ["# CLI flags — every option of every command", "",
           "Generated by `scripts/gen_cli_flags.py` from the real parser (do not edit; `py scripts/gen_cli_flags.py` rewrites it, "
           "a test keeps it current). Every command also takes `--project DIR`. Where the parser has no help text the meaning is read from the code. "
           "`dh <command> --help` lists the positional actions. `dh tryon` passes through to the try-on engine (`references/50-tryon.md`).", "",
           "| command | flag | meaning |", "|---|---|---|"]
    for name, fl in commands():
        for i, (f, h) in enumerate(fl):
            out.append(f"| {'`dh ' + name + '`' if i == 0 else ''} | `{f}` | {h} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    text = table()
    if a.check:
        cur = OUT.read_bytes().decode("utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if cur != text:
            print("cli-flags.md is stale: run py scripts/gen_cli_flags.py")
            return 1
        return 0
    OUT.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print(f"wrote {OUT} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
