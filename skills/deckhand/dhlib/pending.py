"""PENDING: what only the human can do, never only in the chat — two ledgers, one format.

  <project>/PENDING.md       what this project needs from its owner (keys, client facts, clicks, decisions)
  ~/.deckhand/pending.md     the owner's own cross-project items (their accounts, infrastructure) — `--machine`

Line format (agents parse it; on read, a missing WHY/HOW/WHERE is tolerated, never dropped):
  - [ ] P-0NN · what · WHY: consequence if skipped · HOW: the action · WHERE: exact place · asked YYYY-MM-DD
        [· status: open|waiting-confirm] [· nag: yes|no] [· project: name] [· when: trigger]
IDs are per file, zero-padded, next = highest + 1, never reused. Closing: `- [x] … · done YYYY-MM-DD` under ## Done;
dropping: `- [x] … · dropped YYYY-MM-DD · reason`. The checkbox is the state of record, not the heading. A `when:` item
is a deferral the owner decided: it is not re-asked or nagged until its trigger. `decide:` items are decisions that
must survive sessions (shown as DECISION NEEDED). Every report ends with the open items and their age in days.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from .util import DhError, SKILL, home, today

ITEM = re.compile(r"^- \[( |x|X)\] (P-(?:SEO-[\w.]+|\d{3,}))\b(.*)$")
TEMPLATE = "# PENDING — {name}\n\nThings only the owner can do. Agents add a line the moment one appears; nothing lives only in chat.\n" \
           "Format: `- [ ] P-001 · what · WHY: consequence if skipped · HOW: the action · WHERE: exact place · asked YYYY-MM-DD`\n\n## Open\n\n## Done\n"


def machine_path() -> Path:
    return home() / "pending.md"


def path_for(root: Path | None, machine: bool) -> Path:
    if machine or not root or not (Path(root) / ".deckhand").is_dir():
        return machine_path()
    return Path(root) / "PENDING.md"


def _read(p: Path) -> str:
    if p.exists():
        return p.read_text(encoding="utf-8")
    if p == machine_path():
        return TEMPLATE.format(name="the owner (all projects)")
    return (SKILL / "templates" / "PENDING.md").read_text(encoding="utf-8").replace("{{NAME}}", Path(p).parent.name)


def _field(rest: str, key: str) -> str | None:
    m = re.search(r"·\s*" + key + r":\s*([^·]+)", rest)
    return m.group(1).strip() if m else None


def items(p: Path) -> list:
    out = []
    for n, line in enumerate(_read(p).splitlines()):
        m = ITEM.match(line.strip())
        if not m:
            continue
        rest = m.group(3)
        asked = re.search(r"asked (\d{4}-\d{2}-\d{2})", rest)
        what = re.split(r"\s·\s(?:WHY|HOW|WHERE|asked|status|nag|project|when|done|dropped):?", rest, maxsplit=1)[0].strip(" ·")
        out.append({"id": m.group(2), "open": m.group(1) == " ", "what": what, "line": n, "raw": line,
                    "asked": asked.group(1) if asked else None, "status": _field(rest, "status") or "open",
                    "nag": (_field(rest, "nag") or "yes").lower() != "no", "when": _field(rest, "when"), "project": _field(rest, "project"),
                    "decide": what.lower().startswith("decide:")})
    return out


def _age(asked: str | None):
    if not asked:
        return None
    try:
        return (_dt.date.fromisoformat(today()) - _dt.date.fromisoformat(asked)).days
    except ValueError:
        return None


def summary(root: Path | None, include_deferred: bool = False) -> dict:
    """Open items of the project and of the owner's machine ledger, with their age — `dh next` returns them so every
    report ends with them. Deferred (`when:`) and `nag: no` items are counted but not listed."""
    rows, deferred = [], 0
    sources = [("project", Path(root) / "PENDING.md")] if root and (Path(root) / "PENDING.md").exists() else []
    if machine_path().exists():
        sources.append(("machine", machine_path()))
    for src, p in sources:
        for it in items(p):
            if not it["open"]:
                continue
            if (it["when"] or not it["nag"]) and not include_deferred:
                deferred += 1
                continue
            label = ("DECISION NEEDED — " + it["what"][7:].strip()) if it["decide"] else it["what"]
            rows.append({"id": it["id"], "item": label[:160], "age_days": _age(it["asked"]), "from": src,
                         **({"status": it["status"]} if it["status"] != "open" else {}), **({"when": it["when"]} if it["when"] else {})})
    return {"open": len(rows), "items": rows[:14], **({"deferred": deferred} if deferred else {}),
            "say": "end the report with these open items (age in days) — the owner's part is never only in chat"}


def _next_id(text: str) -> str:
    """Highest item ID + 1 — item lines only (the format line of the template shows a sample P-001)."""
    nums = [int(m.group(1)) for line in text.splitlines() if (m := re.match(r"^- \[[ xX]\] P-(\d{3,})\b", line.strip()))]
    return f"P-{(max(nums) + 1) if nums else 1:03d}"


def add(root: Path | None, what: str, why: str = "", how: str = "", where: str = "", machine: bool = False,
        when: str | None = None, project: str | None = None, decide: bool = False, rec: str | None = None) -> dict:
    if not what or not what.strip():
        raise DhError("USAGE", "dh pending add \"what\" --why … --how … --where …")
    if not decide and not (how and where):
        raise DhError("NEED_HOW_WHERE", "a human task needs HOW (the action) and WHERE (the exact place: a path, a URL or a menu chain) — "
                      "the owner has no idea where to look; that is the point of the field")
    from .util import SECRET_RX, mask_tokens
    blob = " ".join(x or "" for x in (what, why, how, where, when, project, rec))
    if SECRET_RX.search(blob) or mask_tokens(blob) != blob:
        raise DhError("SECRET_IN_TEXT", "a pending item names WHERE a secret goes, never the secret itself — "
                      "store it with `dh vault set NAME` and write the name")
    p = path_for(root, machine)
    text = _read(p)
    body0 = (f"decide: {what.strip()}" + (f" (rec: {rec})" if rec else "")) if decide else what.strip()
    same = next((it for it in items(p) if it["open"] and " ".join(it["what"].lower().split()) == " ".join(body0.lower().split())
                 and (it["project"] or "") == (project or "")), None)
    if same:                                            # the same ask twice is one ask
        return {"added": None, "duplicate": same["id"], "file": str(p), "say": f"already open as {same['id']}: {same['what']} — not added again"}
    pid = _next_id(text)
    body = (f"decide: {what.strip()}" + (f" (rec: {rec})" if rec else "")) if decide else what.strip()
    parts = [f"- [ ] {pid} · {body}"] + [f"{k}: {v.strip()}" for k, v in (("WHY", why), ("HOW", how), ("WHERE", where)) if v and v.strip()]
    parts += [f"asked {today()}", "status: open", "nag: " + ("no" if when else "yes")]
    parts += [f"project: {project}"] if project else []
    parts += [f"when: {when}"] if when else []
    line = " · ".join(parts)
    text = _insert_open(text, line)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    label = "DECISION NEEDED" if decide else "ACTION NEEDED"
    return {"added": pid, "file": str(p), "line": line,
            "say": f"{label} — {pid}: {what.strip()}" + (f" · HOW: {how.strip()} · WHERE: {where.strip()}" if not decide else "")
                   + (f" (deferred until: {when})" if when else "")}


def _insert_open(text: str, line: str) -> str:
    lines = text.splitlines()
    if "## Open" not in text:
        return text.rstrip("\n") + "\n\n## Open\n\n" + line + "\n"
    i = lines.index(next(l for l in lines if l.strip() == "## Open")) + 1
    j = i
    while j < len(lines) and not lines[j].startswith("## "):
        j += 1
    while j > i and not lines[j - 1].strip():
        j -= 1
    lines[j:j] = [line]
    return "\n".join(lines) + "\n"


def close(root: Path | None, pid: str, machine: bool = False, drop_reason: str | None = None) -> dict:
    if pid.startswith("P-SEO-"):
        raise DhError("SEO_ITEM", f"{pid} closes itself: put the fact in the brief (`dh brief set seo.…=…`) or record the action, "
                      "then `dh seo audit` — a hand-closed SEO line would come back at the next audit")
    p = path_for(root, machine)
    text = _read(p)
    pid = pid.strip().upper() if pid.strip().lower().startswith("p-") else pid
    hit = next((it for it in items(p) if it["id"].upper() == pid.upper()), None)
    if not hit:
        raise DhError("NO_SUCH_ITEM", f"{pid} is not in {p}")
    if not hit["open"]:
        return {"already": "closed", "id": hit["id"]}
    lines = text.splitlines()
    done = hit["raw"].replace("- [ ]", "- [x]", 1).replace("status: open", "status: done").replace("status: waiting-confirm", "status: done")
    done += f" · dropped {today()} · {drop_reason}" if drop_reason else f" · done {today()}"
    del lines[hit["line"]]
    text = "\n".join(lines) + "\n"
    if "## Done" in text:
        text = text.replace("## Done\n", "## Done\n" + done + "\n", 1) if "## Done\n" in text else text.rstrip("\n") + "\n" + done + "\n"
    else:
        text = text.rstrip("\n") + "\n\n## Done\n" + done + "\n"
    p.write_text(text, encoding="utf-8")
    return {"closed": hit["id"], "as": "dropped" if drop_reason else "done", "file": str(p)}


def set_status(root: Path | None, pid: str, status: str, machine: bool = False) -> dict:
    if status not in ("open", "waiting-confirm"):
        raise DhError("BAD_STATUS", "status: open | waiting-confirm")
    p = path_for(root, machine)
    pid = pid.strip().upper() if pid.strip().lower().startswith("p-") else pid
    hit = next((it for it in items(p) if it["id"].upper() == pid.upper() and it["open"]), None)
    if not hit:
        raise DhError("NO_SUCH_ITEM", f"{pid} is not open in {p}")
    lines = _read(p).splitlines()
    raw = hit["raw"]
    new = re.sub(r"status:\s*[\w-]+", f"status: {status}", raw) if "status:" in raw else raw + f" · status: {status}"
    lines[hit["line"]] = new
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"id": hit["id"], "status": status}


# ------------------------------------------------------------------ the owner's free-form profile notes

def profile_md() -> dict | None:
    """The owner's own notes about themselves (accounts, providers, preferences), written by earlier Deckhand versions
    or by hand: ~/.deckhand/profile.md, plus this project's own profile.md in its layer (`dh profile where`), listed
    first. Fields there are answered: never re-ask them. Read-only here; values that look like secrets are masked
    (the files must not hold any)."""
    from . import profile as PROFILE
    from .util import redact
    paths = [p for p in (PROFILE.project_notes_path(), home() / "profile.md") if p and p.exists()]
    if not paths:
        return None
    facts = []
    for p in paths:
        lines = [redact(l.rstrip()) for l in p.read_text(encoding="utf-8", errors="replace").splitlines()]
        facts += [l.strip("-* ").strip() for l in lines if re.match(r"^\s*[-*]?\s*[\w .()/+-]{2,40}:\s*\S", l) and not l.startswith("#")]
    facts = list(dict.fromkeys(facts))
    return {"path": str(paths[0]), **({"paths": [str(p) for p in paths]} if len(paths) > 1 else {}),
            "facts": facts[:60], "say": "these are answered — never ask for them again"}
