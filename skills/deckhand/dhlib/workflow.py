"""WORKFLOWS: proven paths any AI can follow step by step — query the best 3, pin one, tick it off, improve it with evidence.

A workflow is one JSON file (schema `deckhand.workflow/1`): what it fits (`match`), how proven it is (`proof`), the
questions to ask up front (`ask_upfront`, including the ones past runs learned too late), and the phases → steps with
the exact command, what it must print (`expect`) and what to do when it does not (`on_fail`). `creative` names what the
workflow does NOT decide — where the AI spends its thinking (copy, design, features, the business).

Three pools, one resolution order (like profile and vault):
  mine       ~/.deckhand/workflows/*.json — the owner's own; never leaves the machine unless published
  base       <skill>/workflows/*.json — shipped with Deckhand, curated by its maintainer
  community  workflows/community/ in the Deckhand repo, read through its index (cached); PRs reviewed by the maintainer

Proof levels are computed from the runs a workflow carries, never declared: draft (no complete green run) → proven
(≥1 complete run with 0 unresolved errors) → trusted (≥3 green runs on ≥2 harnesses or systems, and reviewed).
Commands are data an AI will run: `lint` refuses private calls, absolute user paths, secrets and — for base and
community — anything outside the allow-list; `use` shows every non-dh command to the owner before a first run.
Rendered text never carries `{x}` or `<x>` placeholders (Hermes' delegate_task refuses a batch that does).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import urllib.request
from pathlib import Path

from .util import DATA, SKILL, DhError, SECRET_RX, append_jsonl, home, now, read_json, read_jsonl, today, write_json
from . import state as STATE

SCHEMA = "deckhand.workflow/1"
BASE_DIR = SKILL / "workflows"
LEVELS = ("draft", "proven", "trusted")
STEP_KINDS = ("do", "ask", "write", "delegate", "check", "gate")
COMMUNITY_URL = "https://raw.githubusercontent.com/takimdigital/deckhand-skill/main/workflows/community/"
# what a base/community workflow may run besides dh itself: package managers, type/test runners, git, curl reads
ALLOWED = re.compile(r"^((dh|tryon)(\s|$)|(npm|pnpm|yarn|bun) (install|i|ci|add|run|test)\b|npx (--no-install )?(tsc|prisma|drizzle-kit|next|vitest|playwright|eslint)\b"
                     r"|node --test\b|(python3?|py) -m (unittest|pytest)\b|git (add|commit|status|log|diff|push|pull|init|checkout -b|switch -c)\b|curl -s)")
FORBIDDEN = [(re.compile(r"(python3?|py)(\.exe)?\s+-c\b.*(dhlib|_record_base|import)"), "a private call through `py -c` (use a documented dh command)"),
             (re.compile(r"\b_[a-z]\w*\("), "a private function"),
             (re.compile(r"(?i)([A-Z]:\\+Users\\+|/home/[a-z][\w.-]*/|/Users/[A-Za-z][\w.-]*/)"), "an absolute path of one user's machine"),
             (re.compile(r"curl[^|]*\|\s*(ba|z)?sh\b"), "piping a download into a shell"),
             (re.compile(r"\brm\s+-rf\s+(/|~|\$HOME|\*)(\s|$)"), "a destructive delete")]
# checked per command, not in prose: substitution, a hidden `;`, a download piped into an interpreter
SHELL_META = re.compile(r"\$\(|`|;|\|\s*(node|deno|bun|python3?|py|perl|ruby|php|(ba|z|da)?sh|pwsh|powershell)\b|\bwget\b")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")


# ------------------------------------------------------------------ pools

def mine_dir() -> Path:
    return home() / "workflows"


def _cache() -> Path:
    return home() / "cache" / "workflows"


def _sha(wf: dict) -> str:
    return hashlib.sha256(json.dumps(wf, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _community_base() -> str:
    return (os.environ.get("DECKHAND_WORKFLOWS_URL") or COMMUNITY_URL).rstrip("/") + "/"


def _fetch(url: str, timeout: int = 15) -> bytes:
    if url.startswith("file://"):
        return Path(url[7:]).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "deckhand-workflows/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sync(offline: bool = False) -> dict:
    """Refresh the community index (one small file). Offline or unreachable: the cached copy is used, never an error."""
    target = _cache() / "community-index.json"
    if offline:
        return {"synced": False, "cached": target.exists()}
    try:
        idx = json.loads(_fetch(_community_base() + "index.json").decode("utf-8"))
        write_json(target, {**idx, "fetched": now()})
        return {"synced": True, "workflows": len(idx.get("workflows", [])), "from": _community_base()}
    except Exception as e:  # noqa: BLE001
        return {"synced": False, "cached": target.exists(), "why": str(e)[:160]}


def _community_rows(refresh: bool = False) -> list:
    target = _cache() / "community-index.json"
    cur = read_json(target, None, expect=dict)
    if not os.environ.get("DECKHAND_OFFLINE") and (refresh or cur is None or str(cur.get("fetched", ""))[:10] != today()):
        sync()                                          # once a day at most; unreachable = the cached copy
        cur = read_json(target, None, expect=dict)
    return [{**r, "source": "community"} for r in (cur or {}).get("workflows", []) if _row_ok(r)]


def _row_ok(r: dict) -> bool:
    """An index row names files we fetch and cache: only a safe id, an integer version, a plain file name and a sha."""
    return (isinstance(r, dict) and bool(re.match(r"^[a-z0-9][a-z0-9-]{2,63}$", str(r.get("id", "")))) and isinstance(r.get("version"), int)
            and bool(re.match(r"^[a-z0-9][a-z0-9-]{2,63}\.json$", str(r.get("file", f"{r.get('id')}.json"))))
            and bool(re.match(r"^[0-9a-f]{16}$", str(r.get("sha", "")))))


def _files(d: Path) -> list:
    return sorted(p for p in d.glob("*.json") if p.name != "index.json") if d.is_dir() else []


def _median(xs: list):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def row_of(wf: dict, source: str, path: str | None = None) -> dict:
    """The index row: everything `query` scores, nothing more (a pool of thousands costs 3 rows of context)."""
    runs = (wf.get("proof") or {}).get("runs", [])
    green = [r for r in runs if r.get("complete") and not r.get("errors")]
    return {"id": wf["id"], "version": wf.get("version", 1), "title": wf.get("title", ""), "summary": wf.get("summary", "")[:200],
            "source": source, "level": level(wf), "match": wf.get("match", {}),
            "runs": len(runs), "green": len(green), "harnesses": sorted({r.get("harness") for r in green if r.get("harness")}),
            "os": sorted({r.get("os") for r in green if r.get("os")}), "steps": sum(len(p.get("steps", [])) for p in wf.get("phases", [])),
            "minutes": _median([r["minutes"] for r in green if r.get("minutes")]),
            "sha": _sha(wf), **({"path": path} if path else {})}


def rows(refresh: bool = False, sources=("mine", "base", "community")) -> list:
    out = []
    if "mine" in sources:
        out += [row_of(wf, "mine", str(p)) for p in _files(mine_dir()) if (wf := read_json(p, None, expect=dict)) and wf.get("id")]
    if "base" in sources:
        out += [row_of(wf, "base", str(p)) for p in _files(BASE_DIR) if (wf := read_json(p, None, expect=dict)) and wf.get("id")]
    if "community" in sources:
        out += _community_rows(refresh)
    return out


def load(ref: str, refresh: bool = False) -> tuple[dict, str]:
    """`id`, `id@version`, `mine:id`, `base:id`, `community:id` or a file path → (workflow, source). Mine wins, then base."""
    if ref and Path(ref).suffix == ".json" and Path(ref).exists():
        return read_json(Path(ref)), "file"
    src, _, rest = ref.partition(":") if ":" in ref and not re.match(r"^[A-Za-z]:[\\/]", ref) else ("", "", ref)
    wid, _, ver = rest.partition("@")
    for s in ([src] if src else ["mine", "base", "community"]):
        if s == "community":
            hit = next((r for r in _community_rows(refresh) if r["id"] == wid and (not ver or str(r.get("version")) == ver)), None)
            if hit:
                f = _cache() / f"{wid}@{hit.get('version', 1)}.json"
                if not f.exists():
                    try:
                        f.parent.mkdir(parents=True, exist_ok=True)
                        f.write_bytes(_fetch(_community_base() + hit.get("file", f"{wid}.json")))
                    except Exception as e:  # noqa: BLE001
                        raise DhError("UNREACHABLE", f"community workflow {wid}: {e}")
                wf = read_json(f, None, expect=dict)
                if not isinstance(wf, dict) or _sha(wf) != hit["sha"]:
                    f.unlink()
                    raise DhError("SHA_MISMATCH", f"community workflow {wid}: the file does not match its index entry — refused")
                return wf, "community"
            continue
        d = mine_dir() if s == "mine" else BASE_DIR
        for p in _files(d):
            wf = read_json(p, None, expect=dict)
            if wf and wf.get("id") == wid and (not ver or str(wf.get("version")) == ver):
                return wf, s
    raise DhError("NO_SUCH_WORKFLOW", f"{ref}: not in your workflows, the base set or the community index (`dh workflow list`)")


# ------------------------------------------------------------------ proof

def level(wf: dict) -> str:
    runs = (wf.get("proof") or {}).get("runs", [])
    green = [r for r in runs if r.get("complete") and not r.get("errors")]
    envs = {(r.get("harness"), r.get("os")) for r in green}
    if len(green) >= 3 and (len({h for h, _ in envs}) >= 2 or len({o for _, o in envs}) >= 2) and (wf.get("proof") or {}).get("reviewed"):
        return "trusted"
    return "proven" if green else "draft"


# ------------------------------------------------------------------ lint

def _dh_ok(cmd: str) -> str | None:
    """A `dh …` command must exist in this Deckhand: subcommand and action are checked against the real parser."""
    from .cli import build_parser
    try:
        toks = shlex.split(cmd)
    except ValueError:
        return "unbalanced quotes"
    if len(toks) < 2:
        return "a dh call without its subcommand"
    sub = next(a for a in build_parser()._actions if a.__class__.__name__ == "_SubParsersAction")
    if toks[1] not in sub.choices:
        return f"`dh {toks[1]}` does not exist"
    p = sub.choices[toks[1]]
    act = next((a for a in p._actions if a.dest == "action" and a.choices), None)
    if act and len(toks) > 2 and not toks[2].startswith("-") and toks[2] not in act.choices:
        return f"`dh {toks[1]} {toks[2]}` does not exist (actions: {', '.join(act.choices)})"
    return None


def lint(wf: dict, strict: bool = True) -> dict:
    """strict (base + community): every command allow-listed. Personal workflows may carry other commands — flagged,
    and shown to the owner by `use` before the first run."""
    errors, warnings = [], []
    if wf.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not re.match(r"^[a-z0-9][a-z0-9-]{2,63}$", str(wf.get("id", ""))):
        errors.append("id: lowercase letters, digits, dashes (3–64)")
    if not isinstance(wf.get("version"), int) or wf["version"] < 1:
        errors.append("version: an integer ≥ 1")
    for k in ("title", "summary"):
        if not wf.get(k):
            errors.append(f"{k} missing")
    m = wf.get("match") or {}
    if not (m.get("deliverable") or m.get("shape") or m.get("industry")):
        errors.append("match: at least one of deliverable, shape, industry (or nothing can find it)")
    qids = {q.get("id") for q in wf.get("ask_upfront", [])}
    for q in wf.get("ask_upfront", []):
        if not q.get("id") or not q.get("q"):
            errors.append("ask_upfront: every question needs id and q")
        if q.get("ask_at") and q["ask_at"] not in ("define", "research", "plan", "build", "brand", "review", "deploy"):
            errors.append(f"{q.get('id')}: ask_at must be a phase")
    ids, n = set(), 0
    phases = wf.get("phases") or []
    if not phases:
        errors.append("no phases")
    for ph in phases:
        if ph.get("id") not in STATE.PHASE_IDS:
            errors.append(f"phase {ph.get('id')!r} is not a Deckhand phase ({', '.join(STATE.PHASE_IDS)})")
        for st in ph.get("steps", []):
            n += 1
            sid = st.get("id")
            where = f"{ph.get('id')}/{sid}"
            if not sid or sid in ids:
                errors.append(f"{where}: step ids must be unique and present")
            ids.add(sid)
            kinds = [k for k in STEP_KINDS if k in st]
            if len(kinds) != 1:
                errors.append(f"{where}: exactly one of {', '.join(STEP_KINDS)}")
                continue
            k = kinds[0]
            if k == "ask":
                miss = [q for q in (st["ask"] if isinstance(st["ask"], list) else [st["ask"]]) if q not in qids]
                if miss:
                    errors.append(f"{where}: asks unknown question(s) {', '.join(miss)}")
            if k in ("do", "check", "gate") and not st.get("expect"):
                errors.append(f"{where}: `expect` missing (what the command must print — the step's proof)")
            text = " ".join(str(st.get(x, "")) for x in ("do", "check", "gate", "write", "delegate", "on_fail", "expect"))
            for rx, why in FORBIDDEN:
                if rx.search(text):
                    errors.append(f"{where}: {why}")
            if SECRET_RX.search(text):
                errors.append(f"{where}: a credential-shaped value")
            for cmd in _commands(st.get(k) if k in ("do", "check", "gate") else ""):
                if SHELL_META.search(cmd):
                    errors.append(f"{where}: shell tricks in `{cmd[:60]}` (substitution, `;`, a download piped into an interpreter)")
                elif cmd.startswith("dh "):
                    bad = _dh_ok(cmd)
                    if bad:
                        errors.append(f"{where}: {bad}")
                elif not ALLOWED.match(cmd):
                    (errors if strict else warnings).append(f"{where}: custom command `{cmd[:60]}` (allowed: dh, package managers, tsc/tests, git, curl -s)")
    if n > 120:
        warnings.append(f"{n} steps: split it — a workflow any AI can hold is tight (≤ 120 steps)")
    for p in wf.get("pitfalls", []):
        if p.get("sig"):
            try:
                re.compile(p["sig"])
            except re.error as e:
                errors.append(f"pitfall {p.get('id')}: bad regex ({e})")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "steps": n, "level": level(wf)}


def _commands(text) -> list:
    """The commands in a step: `a && b`, one per line; a trailing `# comment` is not part of it."""
    out = []
    for line in str(text or "").splitlines():
        line = line.split("  #")[0].strip()
        out += [c.strip() for c in re.split(r"\s&&\s|\s;\s", line) if c.strip()]
    return out


# ------------------------------------------------------------------ query

def industries() -> dict:
    return read_json(DATA / "industries.json", {"families": {}}) or {"families": {}}


def normalize_industry(text: str) -> tuple:
    """Free text ("commercial cleaning company") → (industry, family). Longest keyword wins; deterministic."""
    t = (text or "").lower()
    best = None
    for fam, words in industries()["families"].items():
        for w in words:
            if re.search(r"(?<![a-z])(" + re.escape(w.replace("-", " ")) + "|" + re.escape(w) + r")(e?s)?(?![a-z])", t):
                if not best or len(w) > len(best[0]):
                    best = (w, fam)
    return best or (None, None)


def _facet(brief: dict, opts: dict) -> dict:
    ind = opts.get("industry") or brief.get("industry") or ""
    word, fam = normalize_industry(ind or " ".join(str(brief.get(k) or "") for k in ("category", "business")))
    return {"deliverable": opts.get("deliverable") or brief.get("deliverable") or "own", "shape": opts.get("shape") or brief.get("shape"),
            "industry": word or (ind or None), "family": fam,
            "features": [x for x in (opts.get("features") or brief.get("features") or []) if x],
            "harness": opts.get("harness") or harness(), "os": opts.get("os") or os_name()}


def score(row: dict, f: dict) -> tuple:
    m, s, why, miss = row.get("match") or {}, 0, [], []
    lv = row.get("level", "draft")

    def has(key, val):
        v = m.get(key)
        return val and (val in v if isinstance(v, list) else v == val)
    if has("deliverable", f["deliverable"]):
        s += 40
        why.append(f"+40 deliverable {f['deliverable']}")
    elif m.get("deliverable"):
        miss.append(f"made for deliverable {m['deliverable']}")
    if f["industry"] and has("industry", f["industry"]):
        s += 30
        why.append(f"+30 industry {f['industry']}")
    elif f["family"] and (m.get("family") == f["family"] or any(normalize_industry(i)[1] == f["family"] for i in m.get("industry") or [])):
        s += 20
        why.append(f"+20 same family ({f['family']}): the path transfers, the words change")
    if has("shape", f["shape"]):
        s += 15
        why.append(f"+15 shape {f['shape']}")
    feats = set(m.get("features") or [])
    hit = sorted(set(f["features"]) & feats)
    if hit:
        pts = min(30, 10 * len(hit))
        s += pts
        why.append(f"+{pts} features {', '.join(hit)}")
    miss += [f"not covered: {x}" for x in sorted(set(f["features"]) - feats)]
    if f["harness"] in row.get("harnesses", []):
        s += 10
        why.append(f"+10 proven on {f['harness']}")
    if f["os"] in row.get("os", []):
        s += 10
        why.append(f"+10 proven on {f['os']}")
    s += {"trusted": 15, "proven": 5, "draft": -15}[lv]
    why.append({"trusted": "+15 trusted", "proven": "+5 proven", "draft": "-15 draft (no complete green run yet)"}[lv])
    if row["source"] == "mine":
        s += 50
        why.append("+50 your own workflow")
    elif row["source"] == "community" and not row.get("reviewed"):
        s -= 10
        why.append("-10 community, not reviewed yet")
    return s, why, miss


def query(brief: dict, opts: dict, top: int = 3, refresh: bool = False) -> dict:
    f = _facet(brief, opts)
    minlv = opts.get("min_level") or "draft"
    out, seen = [], 0
    for r in rows(refresh):
        if LEVELS.index(r.get("level", "draft")) < LEVELS.index(minlv):
            continue
        seen += 1
        s, why, miss = score(r, f)
        if s <= 0:
            continue
        out.append({"ref": f"{r['source']}:{r['id']}@{r['version']}", "title": r["title"], "score": s, "level": r["level"],
                    "proof": f"{r['green']} green run(s) of {r['runs']}" + (f", median {r['minutes']} min" if r.get("minutes") else "")
                             + (f", on {', '.join(r['harnesses'])}" if r.get("harnesses") else ""),
                    "reasons": why, "missing": miss, "steps": r["steps"]})
    out.sort(key=lambda x: (-x["score"], x["ref"]))
    return {"for": f, "top": out[:top], "considered": seen, "matched": len(out),
            "say": ("show the owner these paths (title, proof, what is missing) and let them pick one — or none: "
                    "we start fresh and draft a new workflow as we go") if out else
                   "no workflow fits: follow `dh next`; at the end `dh workflow new --from-run` turns this run into one",
            "then": f"dh workflow use {out[0]['ref']}" if out else "dh next"}


# ------------------------------------------------------------------ harness / system (for proof and syntax)

def harness() -> str:
    e = os.environ
    if e.get("HERMES_AGENT") or e.get("HERMES_SESSION_ID"):
        return "hermes"
    if e.get("CLAUDECODE") or e.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude-code"
    if any(k.startswith("CODEX_") for k in e):
        return "codex"
    if e.get("CURSOR_TRACE_ID") or e.get("CURSOR_AGENT"):
        return "cursor"
    if e.get("GEMINI_CLI"):
        return "gemini-cli"
    if e.get("OPENCODE") or e.get("OPENCODE_SESSION"):
        return "opencode"
    return "unknown"


def todo_how() -> str:
    """How THIS harness loads the checklist into its own todo list (data/harness.json, `todo`); the markdown form is the fallback."""
    from . import guide
    return guide.harness_row().get("todo", "") + " The markdown form is `dh workflow todo --format md`."


def os_name() -> str:
    return {"nt": "windows"}.get(os.name) or ("macos" if os.uname().sysname == "Darwin" else "linux")


# ------------------------------------------------------------------ render

def params_for(wf: dict, root: Path | None, extra: dict | None = None) -> dict:
    b = read_json(Path(root) / ".deckhand" / "brief.json", {}) if root else {}
    b = b or {}
    vals = {k: (v.get("default") if isinstance(v, dict) else v) for k, v in (wf.get("params") or {}).items()}
    for k in list(vals) + ["business", "category", "audience", "shape", "name"]:
        bv = b.get(k) if k != "name" else ((b.get("brand") or {}).get("name") or b.get("name"))
        if bv:
            vals[k] = ",".join(bv) if isinstance(bv, list) else str(bv)
    if b.get("languages"):
        vals["languages"] = ",".join(b["languages"]) if isinstance(b["languages"], list) else str(b["languages"])
    vals.update({k: v for k, v in (extra or {}).items() if v is not None})
    return vals


def fill(text: str, vals: dict) -> str:
    """{{name}} → value; unknown → [name]. The result never holds {x} or <x> (a Hermes delegate_task refuses those)."""
    return PLACEHOLDER.sub(lambda m: str(vals.get(m.group(1))) if vals.get(m.group(1)) not in (None, "") else f"[{m.group(1)}]", str(text))


def step_line(st: dict, vals: dict, qs: dict | None = None) -> str:
    """One step as a line. An ask step carries its questions and defaults (they must survive a compaction)."""
    k = next(k for k in STEP_KINDS if k in st)
    if k == "ask":
        ids = st["ask"] if isinstance(st["ask"], list) else [st["ask"]]
        qs = qs or {}
        body = "ask the owner in ONE message, defaults proposed: " + " ".join(
            f"{n}) {qs[q]['q']}" + (f" [default: {qs[q]['default']}]" if qs[q].get("default") else "") if q in qs else f"{n}) {q}"
            for n, q in enumerate(ids, 1))
    else:
        body = st[k]
    line = f"{st['id']} {k}: {fill(body, vals)}"
    if st.get("expect"):
        line += f"  → expect: {fill(st['expect'], vals)}"
    if st.get("optional"):
        line += "  (optional)"
    return line


def _qs(wf: dict) -> dict:
    return {q["id"]: q for q in wf.get("ask_upfront", []) if q.get("id")}


def render_md(wf: dict, vals: dict, phase: str | None = None) -> str:
    L = [f"# {wf['title']} — {wf['id']}@{wf.get('version', 1)} ({level(wf)})", "", wf.get("summary", ""), ""]
    if not phase and wf.get("ask_upfront"):
        L += ["## Ask up front (ONE message, defaults proposed)", ""]
        L += [f"- {q['id']}: {fill(q['q'], vals)}" + (f" (default: {fill(q['default'], vals)})" if q.get("default") else "")
              + (f" · asked at {q['ask_at']}" if q.get("ask_at") and q["ask_at"] != "define" else "") for q in wf["ask_upfront"]] + [""]
    for ph in wf.get("phases", []):
        if phase and ph["id"] != phase:
            continue
        L += [f"## {ph['id']}" + (f" — {ph['goal']}" if ph.get("goal") else ""), ""]
        L += [f"- [ ] {step_line(st, vals, _qs(wf))}" for st in ph.get("steps", [])]
        pits = [p for p in wf.get("pitfalls", []) if p.get("at") in {s["id"] for s in ph.get("steps", [])}]
        L += [f"  - pitfall {p['id']} at {p['at']}" + (f" ({', '.join(f'{k}={v}' for k, v in (p.get('when') or {}).items())})" if p.get("when") else "")
              + f": {fill(p['fix'], vals)}" for p in pits]
        L.append("")
    if not phase and wf.get("creative"):
        L += ["## Yours to think about (the workflow does not decide these)", ""] + [f"- {fill(c, vals)}" for c in wf["creative"]] + [""]
    return "\n".join(L)


# ------------------------------------------------------------------ use / progress

def pinned(root: Path) -> dict | None:
    s = STATE.load(root, required=False)
    return (s or {}).get("workflow")


def _pinned_wf(root: Path) -> tuple[dict, dict]:
    pin = pinned(root)
    if not pin:
        raise DhError("NO_WORKFLOW", "no workflow pinned — `dh workflow query`, then `dh workflow use <ref>`")
    wf = read_json(Path(root) / ".deckhand" / "workflow.json", None, expect=dict)
    if not wf or _sha(wf) != pin.get("sha"):
        raise DhError("WORKFLOW_CHANGED", ".deckhand/workflow.json no longer matches the pinned version — `dh workflow use` it again")
    return wf, pin


def custom_commands(wf: dict) -> list:
    return sorted({c for ph in wf.get("phases", []) for st in ph.get("steps", []) for k in ("do", "check")
                   for c in _commands(st.get(k, "")) if not re.match(r"(dh|tryon)\s", c) or SHELL_META.search(c)})


def use(root: Path, ref: str, accept: bool = False, sets: dict | None = None) -> dict:
    wf, src = load(ref)
    lt = lint(wf, strict=src in ("base", "community"))
    if not lt["ok"]:
        raise DhError("WORKFLOW_INVALID", f"{wf.get('id')}: {len(lt['errors'])} lint errors — not pinned", errors=lt["errors"][:12])
    other = custom_commands(wf)
    if other and src in ("community", "mine", "file") and not accept:
        raise DhError("NEEDS_ACCEPT", "this workflow runs commands besides dh: show them to the owner; on their OK, re-run with --accept",
                      commands=other)
    s = STATE.load(root)
    old = s.get("workflow") or {}
    same = old.get("id") == wf["id"] and old.get("sha") == _sha(wf)       # pinned again (after a compaction…): keep the progress
    s["workflow"] = {"id": wf["id"], "version": wf.get("version", 1), "source": src, "sha": _sha(wf), "at": old.get("at") if same else now(),
                     "params": {**old.get("params", {}), **(sets or {})}, "done": old.get("done", []) if same else [],
                     "skipped": old.get("skipped", []) if same else [], "deviations": old.get("deviations", []) if same else []}
    STATE.save(root, s)
    write_json(Path(root) / ".deckhand" / "workflow.json", wf)
    STATE.log(root, {"event": "workflow", "id": wf["id"], "version": wf.get("version", 1), "source": src})
    vals = params_for(wf, root, s["workflow"]["params"])
    unset = sorted({m.group(1) for ph in wf.get("phases", []) for st in ph.get("steps", []) for k in STEP_KINDS if isinstance(st.get(k), str)
                    for m in PLACEHOLDER.finditer(st[k]) if vals.get(m.group(1)) in (None, "")})
    return {"pinned": f"{src}:{wf['id']}@{wf.get('version', 1)}", "level": level(wf), "steps": lt["steps"],
            **({"kept_progress": len(s["workflow"]["done"])} if same else {}),
            "ask_upfront": [{"id": q["id"], "q": fill(q["q"], vals), "default": fill(q.get("default", ""), vals)} for q in wf.get("ask_upfront", [])
                            if q.get("ask_at", "define") == "define"],
            **({"params_unset": unset, "set_them": "dh workflow use " + ref + " " + " ".join(f"--set {u}=…" for u in unset)} if unset else {}),
            "next": "ask the ask_upfront questions in ONE message (defaults proposed), record each answer (`dh note decision`), then `dh next`",
            "todo": "dh workflow todo  # the whole checklist for your harness's todo list"}


def progress(root: Path) -> dict | None:
    """Where the pinned workflow stands: done/skipped steps, the next ones in the current phase, the status line."""
    pin = pinned(root)
    if not pin:
        return None
    try:
        wf, pin = _pinned_wf(root)
    except DhError as e:
        return {"line": f"WORKFLOW {pin.get('id')}@{pin.get('version')} · {e.code}: {e.message}"}
    s = STATE.load(root)
    cur = STATE.current(s)["id"]
    vals = params_for(wf, root, pin.get("params"))
    done = set(pin.get("done", [])) | set(pin.get("skipped", []))
    all_steps = [(ph["id"], st) for ph in wf.get("phases", []) for st in ph.get("steps", [])]
    here = [st for pid, st in all_steps if pid == cur]
    todo_here = [st for st in here if st["id"] not in done]
    nxt = todo_here[0] if todo_here else None
    props = len([p for p in (read_json(Path(root) / ".deckhand" / "autopsy" / "workflow-latest.json", {}) or {}).get("proposals", [])])
    line = (f"WORKFLOW {pin['id']}@{pin['version']} ({level(wf)}) · {cur} {len(here) - len(todo_here)}/{len(here)} · "
            f"{len([1 for _, st in all_steps if st['id'] in done])}/{len(all_steps)} steps · {len(pin.get('deviations', []))} deviations"
            + (f" · {props} proposals waiting (dh autopsy --workflow)" if props else ""))
    qs = _qs(wf)
    return {"ref": f"{pin['source']}:{pin['id']}@{pin['version']}", "phase": cur, "next_step": step_line(nxt, vals, qs) if nxt else None,
            "remaining_here": [step_line(st, vals, qs) for st in todo_here[:8]], "line": line,
            "pitfalls": [f"{p['id']}: {fill(p['fix'], vals)}" for p in wf.get("pitfalls", []) if nxt and p.get("at") == nxt["id"] and _when(p)]}


def _when(p: dict) -> bool:
    w = p.get("when") or {}
    return (not w.get("os") or w["os"] == os_name()) and (not w.get("harness") or w["harness"] == harness())


def todo(root: Path, fmt: str = "json", phase: str | None = None) -> dict:
    wf, pin = _pinned_wf(root)
    vals = params_for(wf, root, pin.get("params"))
    done, skipped = set(pin.get("done", [])), set(pin.get("skipped", []))
    s = STATE.load(root)
    cur = STATE.current(s)["id"]
    items, first_open = [], True
    for ph in wf.get("phases", []):
        if phase and ph["id"] != phase:
            continue
        for st in ph.get("steps", []):
            status = "completed" if st["id"] in done | skipped else ("in_progress" if first_open and ph["id"] == cur else "pending")
            if status == "in_progress":
                first_open = False
            items.append({"id": st["id"], "phase": ph["id"], "content": step_line(st, vals, _qs(wf)), "status": status,
                          "activeForm": f"{ph['id']} {st['id']}"})
    md = "\n".join(f"- [{'x' if i['status'] == 'completed' else ' '}] {i['content']}" for i in items)
    out = {"workflow": f"{pin['id']}@{pin['version']}", "count": len(items), "open": len([i for i in items if i["status"] != "completed"])}
    if fmt == "md":
        return {**out, "markdown": md}
    return {**out, "todo": items, "how": todo_how()}


def step(root: Path, sid: str, action: str, why: str = "") -> dict:
    wf, pin = _pinned_wf(root)
    ids = [st["id"] for ph in wf.get("phases", []) for st in ph.get("steps", [])]
    if sid not in ids:
        raise DhError("NO_SUCH_STEP", f"{sid} is not a step of {pin['id']} ({', '.join(ids[:12])}…)")
    if action == "skip" and not why:
        raise DhError("NEED_REASON", "a skipped step needs --why (the autopsy weighs it)")
    s = STATE.load(root)
    w = s["workflow"]
    key = "done" if action == "done" else "skipped"
    if sid not in w[key]:
        w[key].append(sid)
    if action == "skip":
        w["deviations"].append({"at": now(), "kind": "skipped", "step": sid, "why": why})
    STATE.save(root, s)
    return {"step": sid, "status": key, **(progress(root) or {})}


def _norm(cmd: str) -> str:
    """Compare commands by their stable head: `dh plan split --agents 4` ~ `dh plan split`; paths and quotes dropped."""
    cmd = re.sub(r"^\S*(python3?|py)(\.exe)?\s+\S*dh\.py\b", "dh", cmd.strip())
    toks = [t for t in re.split(r"\s+", cmd) if t and not t.startswith("-") and not re.search(r"[\\/\"'={]|^\[", t)]
    if toks[:1] == ["dh"]:
        keep = 4 if len(toks) > 3 and re.match(r"^(G[1-4]|" + "|".join(STATE.PHASE_IDS) + r")$", toks[3]) else 3
        return " ".join(toks[:keep])
    return " ".join(toks[:2])


# building commands no step named = a deviation. Owner-driven moves (brief, gates, reopen, phase skip) are decisions,
# weighed by the autopsy's question ledger, not path deviations.
STATEFUL = re.compile(r"^dh (clone|adopt|scaffold|compose|base record|dev (start|add)|rebrand apply|seo apply|"
                      r"plan (init|split|render)|research (verify|merge)|verify|deploy (ship|target)|handoff|harvest|tryon)")


def observe(root: Path, shown: str, code: int) -> None:
    """After every dh command (and every `dh run -- …`): tick the step it completes; a state-changing command no step
    asked for is a deviation (the workflow autopsy weighs it). Never raises."""
    try:
        s = STATE.load(root, required=False)
        if not s or not s.get("workflow") or code != 0:
            return
        wf = read_json(Path(root) / ".deckhand" / "workflow.json", None, expect=dict)
        if not wf:
            return
        w = s["workflow"]
        before = json.dumps(w, sort_keys=True)
        cmd = re.sub(r"^dh\s+(--project\s+\S+\s+)?", "dh ", shown.strip())
        cmd = re.sub(r"^dh run (--\w+\s+)*--\s+", "", cmd)
        n = _norm(cmd)
        if not n:
            return
        cur = STATE.current(s)["id"]
        done = set(w["done"]) | set(w["skipped"])
        cands = [(ph["id"], st) for ph in wf.get("phases", []) for st in ph.get("steps", []) if st["id"] not in done
                 and any(_norm(c) == n for k in ("do", "check", "gate") for c in _commands(st.get(k, "")))]
        cands.sort(key=lambda x: (x[0] != cur, STATE.PHASE_IDS.index(x[0]) if x[0] in STATE.PHASE_IDS else 99))
        exits = {_norm(c) for ph in wf.get("phases", []) for c in _commands(ph.get("exit", ""))}
        if cands:
            w["done"].append(cands[0][1]["id"])
        elif STATEFUL.match(cmd) and n not in exits:
            w["deviations"].append({"at": now(), "kind": "unplanned", "phase": cur, "cmd": cmd[:160]})
        m = re.match(r"^dh phase (done|skip) (\w+)(?:.*--reason\s+(.+))?", cmd)
        if m:                                           # a finished phase leaves no silent gap
            for ph in wf.get("phases", []):
                if ph["id"] != m.group(2):
                    continue
                open_ = [st for st in ph.get("steps", []) if st["id"] not in set(w["done"]) | set(w["skipped"])]
                if m.group(1) == "skip":                # the owner skipped the phase: one fact, not a step-by-step list
                    w["skipped"] += [st["id"] for st in open_ if "gate" not in st]
                    if [st for st in open_ if not st.get("optional") and "gate" not in st]:
                        w["deviations"].append({"at": now(), "kind": "phase-skipped", "phase": ph["id"], "why": (m.group(3) or "")[:160]})
                    continue
                for st in open_:
                    if "gate" in st:
                        continue                         # the gate comes after the phase: `dh gate pass` ticks it
                    if any(k in st for k in ("ask", "write", "delegate")) or st.get("optional"):
                        w["done"].append(st["id"])       # not observable from commands: the Q&A ledger and the checks judge them
                    else:
                        w["skipped"].append(st["id"])
                        w["deviations"].append({"at": now(), "kind": "not-run", "step": st["id"], "phase": ph["id"]})
        if json.dumps(w, sort_keys=True) != before:          # read-only commands leave run.json untouched
            STATE.save(root, s)
    except Exception:  # noqa: BLE001 — observing never breaks a command
        pass


# ------------------------------------------------------------------ create / save / publish

ABBR = {"define": "DF", "research": "RS", "plan": "PL", "build": "BD", "brand": "BR", "tryon": "TO", "review": "RV", "deploy": "DP", "operate": "OP"}
QUESTION_OF = {"deliverable": ("Who is this for: your own business, a client, or a product you sell to many businesses?", "own"),
               "shape": ("What kind of app: saas, booking, catalogue, marketplace, leadgen or internal?", "saas"),
               "languages": ("Which languages (first = default)?", "en"),
               "audience": ("Who uses it (roles) and who pays?", ""),
               "category": ("In 3–5 words, what is it (used for research queries)?", ""),
               "mode": ("Stop at each gate for your go (phased), or run through (auto)?", "phased")}


def new_from_run(root: Path, wid: str | None = None, title: str | None = None) -> dict:
    """Extract this run as a draft workflow in the owner's pool: the phases it went through, the state-changing commands
    that succeeded (in order, paths made generic), the questions the brief answered, the owner's decisions as learned
    questions. Deterministic; the owner's facts are never copied (only which questions were asked)."""
    root = Path(root)
    s = STATE.load(root)
    b = read_json(root / ".deckhand" / "brief.json", {}) or {}
    runs = read_jsonl(root / ".deckhand" / "runs.jsonl")
    wid = wid or re.sub(r"[^a-z0-9]+", "-", f"{b.get('deliverable') or 'own'}-{b.get('shape') or 'app'}-{normalize_industry(str(b.get('category') or b.get('business') or ''))[0] or 'business'}").strip("-")
    phases, cur, errors = {}, "define", 0
    params = {}
    proj = str(root.resolve())
    for r in runs:
        cmd = str(r.get("cmd") or "")
        cmd = re.sub(r"^\S*(python3?|py)(\.exe)?\s+\"?\S*dh\.py\"?", "dh", cmd).replace(proj, ".").replace(proj.replace("\\", "/"), ".")
        cmd = re.sub(r"\s--project\s+\S+", "", cmd)
        if r.get("exit"):
            errors += 1
            continue
        m = re.match(r"^dh phase (done|skip) (\w+)", cmd)
        if not (STATEFUL.match(cmd) or ALLOWED.match(cmd)) or cmd.startswith("dh workflow"):
            continue
        if re.match(r"^dh (gate pass|note)", cmd):
            continue                                      # quotes and notes are the owner's words, not the path
        bm = re.match(r"^dh brief set\s+(.*)$", cmd)
        if bm:                                            # F12: the step stays (define needs the brief); its VALUES become the next owner's
            keys = list(dict.fromkeys(re.findall(r"(?:^|\s)([a-z][\w.]*)=", bm.group(1))))
            if not keys:
                continue
            cmd = "dh brief set " + " ".join(f'{k}="{{{{{k.replace(".", "_")}}}}}"' for k in keys)
            for k in keys:
                params.setdefault(k.replace(".", "_"), {"default": "", "why": f"the owner's answer for brief.{k} (asked at define)"})
        steps = phases.setdefault(cur, [])
        if not any(_norm(x["do"]) == _norm(cmd) for x in steps):
            steps.append({"id": f"{ABBR[cur]}{len(steps) + 1}", "do": cmd, "expect": "ok: true"})
        if m:
            cur = STATE.PHASE_IDS[min(STATE.PHASE_IDS.index(m.group(2)) + 1, len(STATE.PHASE_IDS) - 1)]
    asked = [{"id": f"Q-{k}", "q": QUESTION_OF[k][0], "default": QUESTION_OF[k][1], "ask_at": "define"} for k in QUESTION_OF if b.get(k) or k == "mode"]
    from . import resume as RESUME
    for n in RESUME.notes(root):
        if n.get("kind") == "decision":
            asked.append({"id": f"Q-learned-{len(asked) + 1}", "q": f"(learned) settle up front: {n['text'][:140]}", "ask_at": "define",
                          "learned_from": f"{s.get('name')} {str(n.get('at', ''))[:10]} — decided mid-run"})
    ind, fam = normalize_industry(str(b.get("category") or b.get("business") or ""))
    wf = {"schema": SCHEMA, "id": wid, "version": 1, "title": title or f"{(b.get('deliverable') or 'own').title()} {b.get('shape') or 'app'}" + (f" for {ind}" if ind else ""),
          "summary": f"Extracted from the run of {s.get('name')} ({today()}). A draft until a complete run follows it without errors.",
          "match": {"deliverable": [b.get("deliverable") or "own"], **({"shape": [b["shape"]]} if b.get("shape") else {}),
                    **({"industry": [ind], "family": fam} if ind else {}), "features": b.get("features") or []},
          "proof": {"runs": [{"date": today(), "harness": harness(), "os": os_name(), "errors": errors,
                              "complete": s["phases"].get("deploy", {}).get("status") in ("done", "skipped"), "source": "new --from-run"}]},
          "ask_upfront": asked, "params": params,
          "phases": [{"id": pid, "steps": st, "exit": f"dh phase done {pid}"} for pid, st in phases.items() if st],
          "pitfalls": [], "creative": ["the copy on every page", "the design direction", "features beyond the plan", "the business around it"],
          "changelog": [{"version": 1, "date": today(), "change": "extracted from a run", "why": "a path that worked once", "evidence": f"runs.jsonl of {s.get('name')}"}]}
    for ph in wf["phases"]:
        for st in ph["steps"]:
            st["do"] = re.sub(r"(--to|--project)\s+\S+", r"\1 {{dir}}", st["do"])
    path = mine_dir() / f"{wid}.json"
    lt = lint(wf, strict=False)
    write_json(path, wf)
    return {"saved": str(path), "id": wid, "level": level(wf), "steps": lt["steps"], "lint": {k: lt[k] for k in ("ok", "errors", "warnings")},
            "next": f"read it (dh workflow show mine:{wid}), tighten the steps (expect lines), then use it on the next similar project"}


def save(wf: dict, where: str = "mine") -> dict:
    """mine → ~/.deckhand/workflows (a base/community workflow becomes your fork); public → an outbox bundle for a PR."""
    lt = lint(wf, strict=where == "public")
    if not lt["ok"]:
        raise DhError("WORKFLOW_INVALID", f"{len(lt['errors'])} lint errors", errors=lt["errors"][:12])
    if where == "public":
        return publish_bundle(wf)
    path = mine_dir() / f"{wf['id']}.json"
    write_json(path, wf)
    return {"saved": str(path), "ref": f"mine:{wf['id']}@{wf['version']}", "level": level(wf)}


def publish_bundle(wf: dict) -> dict:
    from .util import redact
    lt = lint(wf, strict=True)
    if not lt["ok"]:
        raise DhError("WORKFLOW_INVALID", "community workflows are strict: fix these first", errors=lt["errors"][:12])
    text = json.dumps(wf, indent=2, ensure_ascii=False)
    if redact(text) != text:
        raise DhError("SECRETS", "a credential-shaped value is in the workflow — remove it")
    out = mine_dir() / "outbox" / f"{wf['id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    return {"bundle": str(out), "level": level(wf),
            "submit": ["fork github.com/takimdigital/deckhand-skill", f"copy the bundle to workflows/community/{wf['id']}.json",
                       "python3 scripts/workflows_index.py   # rebuilds workflows/community/index.json and lints every file",
                       "open a pull request: what it builds, the runs that prove it — the maintainer reviews before it is listed"],
            "note": "nothing was sent anywhere: the owner decides to publish"}


def add_run(wf: dict, run_: dict) -> dict:
    wf = json.loads(json.dumps(wf))
    wf.setdefault("proof", {}).setdefault("runs", []).append(run_)
    return wf


def history(root: Path) -> list:
    return [h for h in read_jsonl(Path(root) / ".deckhand" / "history.jsonl") if h.get("event") == "workflow"]


def log_event(root: Path, event: dict) -> None:
    append_jsonl(Path(root) / ".deckhand" / "history.jsonl", {"at": now(), **event})
