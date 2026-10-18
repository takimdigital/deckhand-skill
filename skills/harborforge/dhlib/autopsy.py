"""AUTOPSY: a session in, evidence-based improvements out — deterministic, no model, no opinion.

Sources (auto-detected):
  claude  Claude Code session JSONL (~/.claude/projects/<project-slug>/<session>.jsonl) — `--latest` finds it
  runs    deckhand's own run log (.deckhand/runs.jsonl): every `dh …` call and every `dh run -- …` — works the
          same in any harness (Hermes, Codex, Cursor…) as long as risky commands go through `dh run`
  plain   JSONL of {"cmd": "…", "exit": 0, "out": "…"} (or {"edit": "path"}) — anything can emit it

Pipeline:
  events → failures (a non-zero exit, OR error markers in the output of an executing command, because
  `cmd | tail` hides exit codes) → episodes (a failure signature, its retries, and everything until the same
  command family succeeded) → the working recipe (the state-changing commands and edited files between the
  LAST failed attempt and the success) → an owner (skill · environment · project; scratch and exploration are
  never episodes, tool errors are listed apart) → the
  strongest fix-ladder rung the evidence supports (eliminate > preflight > reorder > gate > pitfall).

Artifacts:
  .deckhand/autopsy/<id>.md|.json   the report — same input, same bytes
  --apply                           lessons WITH recipes into ~/.deckhand/lessons.jsonl (the owner's ledger:
                                    `dh run` prints the recipe the moment the error reappears, `--fix` replays
                                    the auto-safe ones), skill proposals into ~/.deckhand/autopsy/proposals/
                                    (repro + the fix that worked + the regression test it needs), and
                                    playbooks (successful phase runs) into ~/.deckhand/playbooks.jsonl
  The skill itself is never edited by the autopsy: a proposal is applied by a person or a reviewed PR.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from pathlib import Path

from .util import DhError, append_jsonl, is_guard, home, now, read_jsonl, write_json
from . import redact as RD

RUNG_ORDER = ("pitfall", "gate", "reorder", "preflight", "eliminate")
READ_ONLY = {"cd", "echo", "ls", "cat", "head", "tail", "grep", "rg", "egrep", "fgrep", "sed", "awk", "wc", "sort", "uniq", "cut",
             "tr", "true", "false", "sleep", "printf", "pwd", "test", "[", "which", "type", "find", "stat", "file", "du", "df",
             "date", "basename", "dirname", "tee", "jq", "less", "more", "diff", "cmp", "ps", "whoami", "id", "uname", "env",
             "export", "set", "unset", "source", ".", "xxd", "od", "md5sum", "sha1sum", "sha256sum", "tree", "realpath", "readlink",
             "git status", "git log", "git show", "git diff", "git branch", "git rev-parse", "git remote", "git ls-files", "curl"}
EXECUTING = re.compile(r"^(npm|pnpm|yarn|bun|npx|node|python|python3|py|pytest|dh|tsc|next|vite|cargo|go|make|docker|git push|git commit|git merge|pip|uv|deno|playwright)\b")
MARKERS = re.compile(r"(error TS\d+|Traceback \(most recent call last\)|^\s*not ok \d+|^# fail [1-9]|\b[1-9]\d* failed\b|^FAIL\b|^FAILED\b|\bFAILED \(|npm ERR!|ERR_PNPM_\w+"
                     r"|^\s*\w*(Syntax|Type|Reference|Range)Error: |Cannot find module|Module not found|Failed to compile|Build error"
                     r"|command not found|No such file or directory|Permission denied|^fatal: |\bENOENT\b|\bEACCES\b|\bECONNREFUSED\b|\bETIMEDOUT\b"
                     r"|\"ok\": ?false|UnhandledPromiseRejection|^Error: )", re.M)
SPECIFIC = re.compile(r"(error TS\d+|Module not found|Cannot find module|^\s*not ok \d+|\w*Error: \S|ERR!\s+\S|\bP\d{4}:|\bE[A-Z]{3,}\b: )")
FAILWORDS = re.compile(r"(failed|error|denied|refused|rejected|not found|cannot|can't|unable|invalid|timed? ?out|forbidden|unauthori[sz]ed)", re.I)
CRASH_RX = re.compile(r"(Traceback \(most recent call last\)|^\s+at .*(skills/deckhand|\.deckhand/skill)|UnhandledPromiseRejection|\"code\": ?\"(ERROR|PARSE_FAILED|WRAPPER_MISSING|INTERNAL)\")", re.M)
ENV_RX = re.compile(r"(command not found|not found on PATH|EACCES|Permission denied|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|EGRESS"
                    r"|403 Forbidden|\b403\b|not accessible by integration|proxy|ENOSPC|No space left|killed by signal|rate limit|certificate)", re.I)
GENERATED_RX = re.compile(r"components/(dh-tryon|sections|ui-kit)/")
CONFIG_RX = re.compile(r"(^|/)(next\.config\.\w+|vite\.config\.\w+|tsconfig\.json|package\.json|\.env[\w.]*|[\w.-]+\.config\.\w+|components\.json|globals\.css)$")
SAFE_RX = re.compile(r"^(npm (i|install|ci)\b|pnpm (i|install|add)\b|yarn( install| add)?\b|bun (i|install|add)\b|pip3? install\b|uv (add|sync)\b"
                     r"|npx prisma generate\b|rm -rf (\.next|node_modules/\.cache|\.turbo|dist|build)\b|mkdir -p\b|git config\b|npx next telemetry\b)")
SKILL_RX = re.compile(r"(skills/deckhand/|\.deckhand/skill/|/deckhand/(dh\.py|tryon/)|(^|\s)dh(\s|$)|dh\.py|tryon/cli\.mjs|compose\.mjs)")
TEST_FILE_RX = re.compile(r"(^|/)(tests?|__tests__)/|\.(test|spec)\.\w+$|(^|/)test_\w+\.py$")
TEST_RUNNER = re.compile(r"^((node|bun|deno) --test|(python3?|py) -m (unittest|pytest)|pytest|(npm|pnpm|yarn|bun) (run )?test\b|npx (vitest|jest|playwright))")
VERIFY = re.compile(r"^((node|bun|deno) --test|(python3?|py) -m (unittest|pytest)|pytest|(npm|pnpm|yarn|bun) (run )?(test|build|lint|typecheck|check)\b|npx (tsc|vitest|jest|playwright|eslint|next build)|tsc|git (add|commit|push|status|log|diff|tag)|dh (verify|status|next)|(python3?|py) (version_check|leak_sweep)\.py)")
EXIT_MEANING = {124: "timed out", 126: "not executable", 127: "command not found", 130: "interrupted", 137: "killed (SIGKILL / out of memory)",
                143: "terminated (SIGTERM)", 144: "killed by signal — often a kill/pkill pattern that matched the agent's own shell"}


# ------------------------------------------------------------------ sources

def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _epoch(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if not v:
        return None
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


INJECTED = re.compile(r"^(ASYNC DELEGATION BATCH COMPLETE|\[SYSTEM|<system-reminder>|<command-|Caveat:|\[Request interrupted|\[?CONTEXT COMPACTION|"
                      r"⟪?HERMES-CONTEXT-COMPRESSION|This session is being continued|Summary of (the )?earlier conversation)", re.I)


def load_claude(path: Path) -> tuple[list, dict]:
    events, uses, meta = [], {}, {"cwd": None, "session": None, "messages": []}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        meta["cwd"] = meta["cwd"] or d.get("cwd")
        meta["session"] = meta["session"] or d.get("sessionId")
        msg = d.get("message") or {}
        content = msg.get("content")
        ts = _epoch(d.get("timestamp"))
        if d.get("type") in ("user", "assistant") and msg.get("role") in ("user", "assistant") and not d.get("isMeta"):
            text = content if isinstance(content, str) else _text(content)
            if text.strip() and not (isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content)):
                meta["messages"].append({"i": len(meta["messages"]), "role": msg["role"], "text": text, "ts": ts, "injected": bool(INJECTED.match(text.strip()))})
        if not isinstance(content, list):
            continue
        for x in content:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "tool_use":
                name, inp = x.get("name"), x.get("input") or {}
                if name == "Bash":
                    ev = {"kind": "cmd", "cmd": str(inp.get("command", "")), "bg": bool(inp.get("run_in_background"))}
                elif name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
                    ev = {"kind": "edit", "file": str(inp.get("file_path") or inp.get("notebook_path") or "")}
                else:
                    ev = {"kind": "tool", "tool": name}
                ev["i"] = len(events)
                ev["ts"] = ts
                events.append(ev)
                uses[x.get("id")] = ev
            elif x.get("type") == "tool_result":
                ev = uses.get(x.get("tool_use_id"))
                if not ev:
                    continue
                out = _text(x.get("content"))
                if ev["kind"] == "cmd":
                    m = re.match(r"Exit code (\d+)\s*\n?", out)
                    ev["exit"] = int(m.group(1)) if m else (1 if x.get("is_error") else 0)
                    ev["out"] = out[m.end():] if m else out
                    if ev.get("bg") and not m:
                        ev["exit"] = None                                   # a background start says nothing yet
                else:
                    ev["exit"] = 1 if x.get("is_error") else 0
                    ev["out"] = out
    return events, meta


def load_runs(path: Path) -> tuple[list, dict]:
    events = []
    for r in read_jsonl(path):
        if r.get("edit"):
            events.append({"i": len(events), "kind": "edit", "file": r["edit"]})
            continue
        cmd = r.get("cmd") or ""
        code = r.get("exit", r.get("code"))
        if is_guard(r):
            continue                                        # Deckhand refusing on purpose (a gate, a quote): a decision, not a failure
        events.append({"i": len(events), "kind": "cmd", "cmd": cmd, "exit": code if isinstance(code, int) else (0 if code is None else 1),
                       "out": r.get("out") or r.get("tail") or "", "trusted": True, "ts": _epoch(r.get("at"))})
    return events, {"cwd": str(path.parent.parent) if path.parent.name == ".deckhand" else None, "session": path.stem}


def _hermes_rows(rows: list, meta: dict) -> list:
    """Hermes messages (state.db rows or an export's messages): role, content, tool_calls (JSON), tool_call_id,
    tool_name, timestamp. `terminal` calls become commands (exit from the result's exit_code), the rest tool calls."""
    events, uses = [], {}
    for r in rows:
        role, content, ts = r.get("role"), r.get("content"), _epoch(r.get("timestamp"))
        text = content if isinstance(content, str) else _text(content) if content else ""
        calls = r.get("tool_calls")
        if isinstance(calls, str):
            try:
                calls = json.loads(calls)
            except ValueError:
                calls = []
        if role in ("user", "assistant") and text and text.strip():
            meta["messages"].append({"i": len(meta["messages"]), "role": role, "text": text, "ts": ts, "id": r.get("id"),
                                     "injected": bool(INJECTED.match(text.strip()))})
        for c in calls or []:
            fn = c.get("function") or c
            name, args = fn.get("name"), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args}
            if name == "terminal":
                ev = {"kind": "cmd", "cmd": str(args.get("command", "")), "bg": bool(args.get("background"))}
            elif name in ("write_file", "patch"):
                ev = {"kind": "edit", "file": str(args.get("path", ""))}
            else:
                ev = {"kind": "tool", "tool": name}
            ev.update({"i": len(events), "ts": ts})
            events.append(ev)
            uses[c.get("id")] = ev
        if role == "tool":
            ev = uses.get(r.get("tool_call_id"))
            if not ev:
                continue
            res = None
            try:
                res = json.loads(text) if text.strip().startswith("{") else None
            except ValueError:
                res = None
            if isinstance(res, dict):
                code = res.get("exit_code", res.get("returncode"))
                bad = res.get("status") == "error" or res.get("success") is False or (res.get("error") not in (None, "", False) and code in (None, 0) and ev["kind"] != "cmd")
                ev["exit"] = int(code) if isinstance(code, int) else (1 if bad else 0)
                ev["out"] = str(res.get("output") or res.get("error") or "")[-6000:]
            else:
                ev["exit"] = 1 if re.match(r"^\s*(error|Error|ERROR)\b", text or "") else 0
                ev["out"] = (text or "")[-6000:]
            if ev.get("bg") and ev["kind"] == "cmd" and ev["exit"] == 0:
                ev["exit"] = None                                   # a background start says nothing yet
    return events


def hermes_home() -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"])
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def load_hermes_db(path: Path, session: str | None = None, project: Path | None = None) -> tuple[list, dict]:
    """Hermes' own store (read-only): the session (HERMES_SESSION_ID, or the latest one run in this project), its
    compression lineage, and the sub-agent batches it dispatched (async_delegations + their live logs)."""
    import sqlite3
    try:
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        con.execute("select 1 from sqlite_master limit 1")
    except sqlite3.Error:
        copy = _db_copy(Path(path))                          # a live, locked store: read a copy (with its WAL)
        try:
            con = sqlite3.connect(copy)
        except BaseException:
            _drop_copy(copy)
            raise
    else:
        copy = None
    con.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "messages" not in tables or "sessions" not in tables:
            raise DhError("UNKNOWN_SOURCE", f"{path}: not a Hermes state.db (no sessions/messages tables)")
        scols = {r[1] for r in con.execute("pragma table_info(sessions)")}
        sid = session or os.environ.get("HERMES_SESSION_ID")
        if not sid:
            q = "select id from sessions" + (" where cwd like ?" if project and "cwd" in scols else "") + " order by started_at desc limit 1"
            row = con.execute(q, ((str(Path(project).resolve()).replace("\\", "/") + "%",) if project and "cwd" in scols else ())).fetchone()
            if not row and project and "cwd" in scols:
                row = con.execute("select id from sessions where replace(cwd, '\\', '/') like ? order by started_at desc limit 1",
                                  (str(Path(project).resolve()).replace("\\", "/") + "%",)).fetchone()
            if not row:
                raise DhError("NO_SOURCE", "no Hermes session found for this project — pass --session ID (hermes sessions list)")
            sid = row[0]
        ids, cur = [], sid
        while cur and cur not in ids:                        # compression lineage: the ancestors first
            ids.insert(0, cur)
            r = con.execute("select parent_session_id from sessions where id = ?", (cur,)).fetchone()
            cur = r[0] if r and "parent_session_id" in scols else None
        frontier = [sid]
        while frontier and "parent_session_id" in scols:      # and the continuations after a split (not the sub-agents)
            nxt = []
            for f in frontier:
                q = "select id from sessions where parent_session_id = ?" + (" and source != 'subagent'" if "source" in scols else "")
                nxt += [r[0] for r in con.execute(q, (f,)) if r[0] not in ids]
            ids += nxt
            frontier = nxt
        mcols = {r[1] for r in con.execute("pragma table_info(messages)")}
        want = [c for c in ("id", "role", "content", "tool_calls", "tool_call_id", "tool_name", "timestamp") if c in mcols]
        rows = [dict(r) for r in con.execute(f"select {', '.join(want)} from messages where session_id in ({','.join('?' * len(ids))}) order by timestamp, id", ids)]
        meta = {"cwd": None, "session": sid, "lineage": ids, "messages": [], "harness": "hermes"}
        if "cwd" in scols:
            r = con.execute("select cwd from sessions where id = ?", (sid,)).fetchone()
            meta["cwd"] = r[0] if r else None
        meta["delegations"] = []
        if "async_delegations" in tables:
            dcols = {r[1] for r in con.execute("pragma table_info(async_delegations)")}
            key = "parent_session_id" if "parent_session_id" in dcols else "origin_session"
            for d in con.execute(f"select * from async_delegations where {key} in ({','.join('?' * len(ids))})", ids):
                d = dict(d)
                tasks, results = _jl(d.get("task_json")), _jl(d.get("result_json"))
                meta["delegations"].append({"id": d.get("delegation_id"), "state": d.get("state"), "at": d.get("dispatched_at"), "done_at": d.get("completed_at"),
                                            "tasks": len(tasks) if isinstance(tasks, list) else None,
                                            "results": [str((x or {}).get("status") or (x or {}).get("state") or "?") for x in results] if isinstance(results, list) else [],
                                            "logs": str(Path(path).parent / "cache" / "delegation" / "live" / str(d.get("delegation_id")))})
    finally:
        con.close()                                          # first: an open sqlite file cannot be deleted on Windows
        _drop_copy(copy)
    return _hermes_rows(rows, meta), meta


def _drop_copy(copy) -> None:
    """Remove the temp copy made by _db_copy (its folder), so a read leaves nothing in the temp dir."""
    if copy:
        from .util import rmtree
        rmtree(Path(copy).parent)


def _db_copy(path: Path) -> str:
    import shutil
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="dh-hermes-"))
    try:
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(path) + suffix)
            if src.exists():
                shutil.copy2(src, d / (path.name + suffix))
    except BaseException:
        from .util import rmtree
        rmtree(d)
        raise
    return str(d / path.name)


def _jl(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    if isinstance(v, dict):
        return v.get("tasks") or v.get("results") or v
    return v


def load_hermes_export(path: Path, session: str | None = None) -> tuple[list, dict]:
    """`hermes sessions export --format jsonl`: one JSON object per session, its messages inside."""
    sess = [d for d in read_jsonl(path) if isinstance(d.get("messages"), list)]
    if session:
        sess = [d for d in sess if session in (d.get("id"), d.get("session_id"))] or sess
    if not sess:
        raise DhError("UNKNOWN_SOURCE", f"{path}: no session with messages")
    d = sess[-1]
    meta = {"cwd": d.get("cwd"), "session": d.get("id") or d.get("session_id"), "messages": [], "harness": "hermes", "delegations": []}
    return _hermes_rows(d["messages"], meta), meta


def load_chat(path: Path) -> tuple[list, dict]:
    """Any harness: JSONL of {"role": "user"|"assistant", "content"|"text": "…", "ts": …} — the conversation only."""
    meta = {"cwd": None, "session": path.stem, "messages": []}
    for d in read_jsonl(path):
        text = d.get("content") if isinstance(d.get("content"), str) else _text(d.get("content")) if d.get("content") else d.get("text", "")
        if d.get("role") in ("user", "assistant") and str(text).strip():
            meta["messages"].append({"i": len(meta["messages"]), "role": d["role"], "text": str(text), "ts": _epoch(d.get("ts") or d.get("timestamp")),
                                     "injected": bool(INJECTED.match(str(text).strip()))})
    return [], meta


def load(path: Path, kind: str, session: str | None = None, project: Path | None = None) -> tuple[list, dict]:
    if kind == "claude":
        return load_claude(path)
    if kind == "hermes-db":
        return load_hermes_db(path, session, project)
    if kind == "hermes-export":
        return load_hermes_export(path, session)
    if kind == "chat":
        return load_chat(path)
    return load_runs(path)


def detect(path: Path) -> str:
    with open(path, "rb") as fb:
        if fb.read(16).startswith(b"SQLite format 3"):
            return "hermes-db"
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d.get("messages"), list):
                return "hermes-export"
            if "sessionId" in d or "message" in d or d.get("type") in ("user", "assistant", "summary", "attachment"):
                return "claude"
            if "cmd" in d or "edit" in d:
                return "runs"
            if d.get("role") in ("user", "assistant", "system") and ("content" in d or "text" in d):
                return "chat"
    raise DhError("UNKNOWN_SOURCE", f"{path}: not a Claude Code transcript, a Hermes state.db or export, a chat log nor a deckhand run log")


def claude_dir_for(project: Path) -> Path:
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path(project).resolve()))


def latest_source(root: Path) -> Path:
    if os.environ.get("HERMES_SESSION_ID") and (hermes_home() / "state.db").exists():
        return hermes_home() / "state.db"                    # inside Hermes: this very session, read-only
    cands = sorted(claude_dir_for(root).glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if claude_dir_for(root).exists() else []
    if cands:
        return cands[-1]
    runs = Path(root) / ".deckhand" / "runs.jsonl"
    if runs.exists():
        return runs
    raise DhError("NO_SOURCE", "no session found: pass a transcript path, or run commands through `dh run -- …` so .deckhand/runs.jsonl exists")


# ------------------------------------------------------------------ command anatomy

def _strip_heredocs(cmd: str) -> str:
    out, skip = [], None
    for line in cmd.split("\n"):
        if skip:
            if line.strip() == skip:
                skip = None
            continue
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            skip = m.group(1)
        out.append(line)
    return "\n".join(out)


def _subst(cmd: str) -> str:
    """Resolve simple `X=/path` assignments so `node $S/t.mjs` is recognisably a scratch script."""
    env = {}
    for m in re.finditer(r"(?:^|[\s;&(])([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)", cmd):
        env[m.group(1)] = m.group(2).strip("'\"")
    for _ in range(2):
        cmd = re.sub(r"\$\{?([A-Za-z_]\w*)\}?", lambda m: env.get(m.group(1), m.group(0)), cmd)
    return cmd


SCRIPTED_EDIT = re.compile(r"^(python3?|py|node|bun|deno)\s+-\s*(<<|$)|^cat\s+>>?\s*\S+|^sed\s+-i|^perl\s+-p?i|^tee\s+\S+|^printf .*>\s*\S+|^echo .*>\s*\S+")


def segments(cmd: str) -> list:
    s = _strip_heredocs(_subst(cmd))
    parts, buf, q, i = [], "", None, 0
    while i < len(s):
        c = s[i]
        if q:
            buf += c
            if c == q:
                q = None
        elif c in "'\"":
            q = c
            buf += c
        elif s.startswith("&&", i) or s.startswith("||", i):
            parts.append(buf); buf = ""; i += 2; continue
        elif c in ";|\n":
            parts.append(buf); buf = ""
        else:
            buf += c
        i += 1
    parts.append(buf)
    return [p.strip() for p in parts if p.strip() and not p.strip().startswith("#")]


def _tokens(seg: str) -> list:
    try:
        t = shlex.split(seg)
    except ValueError:
        t = seg.split()
    while t and (re.match(r"^\w+=", t[0]) or t[0] in ("sudo", "env", "exec", "time", "(", "{")):
        t = t[1:]
    if t and t[0] == "timeout":
        t = [x for x in t[1:] if not re.match(r"^(-\w+|\d+[smh]?)$", x)] if len(t) > 1 else []
    return t


def family(seg: str, trusted: bool = False) -> str | None:
    if SCRIPTED_EDIT.match(seg.strip()):
        return "(edit)"
    t = _tokens(seg)
    if not t:
        return None
    if not trusted and any(re.search(r"(^|/)(tmp|scratchpad)(/|$)|/var/folders/", x) and re.search(r"\.(mjs|cjs|js|ts|py|sh)$", x) for x in t[1:3]):
        return "(scratch)"
    prog = os.path.basename(t[0])
    rest = [x for x in t[1:] if not x.startswith("-")]
    if prog in ("python", "python3", "py", "node", "bash", "sh", "deno", "bun") and t[1:]:
        if len(t) > 1 and t[1] in ("-c", "-e"):
            return prog + " " + t[1]                                    # an inline scratch script
        if len(t) > 2 and t[1] == "-m":
            return f"{prog} -m {t[2]}"
        if t[1] == "--test":
            return prog + " --test"
        if rest and re.search(r"\.(py|mjs|cjs|js|ts|sh)$", rest[0]):
            sub = next((x for x in rest[1:] if re.match(r"^[a-z][\w:-]*$", x)), "")
            return f"{prog} {os.path.basename(rest[0])}" + (f" {sub}" if sub else "")
    if prog in ("npm", "pnpm", "yarn", "npx", "git", "dh", "docker", "pip", "pip3", "cargo", "go", "uv", "gh", "make"):
        if prog in ("npm", "pnpm", "yarn") and rest[:1] == ["run"] and len(rest) > 1:
            return f"{prog} run {rest[1]}"
        return prog + (" " + rest[0] if rest else "")
    return prog


def families(cmd: str, trusted: bool = False) -> list:
    out, in_tmp = [], False
    for seg in segments(cmd):
        t = _tokens(seg)
        if t and t[0] == "cd":
            in_tmp = bool(len(t) > 1 and re.search(r"(^|/)(tmp|scratchpad)(/|$)|/var/folders/", t[1]))
            f = "cd"
        else:
            f = family(seg, trusted)
            if in_tmp and not trusted and f and not _is_read_only(f) and f not in ("(edit)",) and re.match(r"^(node|python3?|py|bash|sh|bun|deno) \S+\.(mjs|cjs|js|ts|py|sh)", f):
                f = "(scratch)"                                     # a relative script run inside a scratch folder
        if f and f not in out:
            out.append(f)
    return out


def _is_read_only(f: str) -> bool:
    return f in READ_ONLY or f.split(" ")[0] in READ_ONLY and f.split(" ")[0] not in ("git",)


def _aside(f: str) -> bool:
    """Not the command's purpose: helpers, inline/scratch scripts, scripted file edits."""
    return _is_read_only(f) or f in ("(edit)", "(scratch)") or f.endswith(" -c") or f.endswith(" -e")


def primary(cmd: str, trusted: bool = False) -> list:
    """The families that carry the command's meaning — empty for pure exploration, scratch or edit scripts."""
    return [f for f in families(cmd, trusted) if not _aside(f)]


def _scratch(cmd: str) -> bool:
    return not primary(cmd)


def edits_in(cmd: str) -> list:
    """Files a command writes as an edit (cat > f, sed -i … f, python3 - <<EOF with p = 'f')."""
    cmd = _subst(cmd)
    out = [m.group(1) for m in re.finditer(r"(?:^|[\s;&])cat\s+>>?\s*([^\s;&|<]+)", cmd)]
    out += [m.group(1) for m in re.finditer(r"(?:^|[\s;&])sed\s+-i\S*\s+(?:'[^']*'|\"[^\"]*\"|\S+)\s+([^\s;&|]+)", cmd)]
    if re.search(r"(python3?|py)\s+-\s*<<", cmd):
        out += re.findall(r"\bp\s*=\s*['\"]([^'\"]+\.\w+)['\"]", cmd)
    return sorted(set(out))


def display(cmd: str, meta: dict | None = None) -> str:
    keep = [x for x in segments(cmd) if not _aside(family(x) or "")] or segments(cmd)[:1]
    return _paths_to(" && ".join(keep), meta or {})[:180]


def _last_prog(cmd: str) -> str:
    segs = segments(cmd)
    return family(segs[-1]) if segs else ""


def is_failure(ev: dict) -> tuple[bool, bool]:
    """(failed, masked). grep/diff/test exit 1 is an answer, not a failure; pipes hide exit codes."""
    if ev.get("kind") != "cmd" or ev.get("exit") is None:
        return (ev.get("kind") in ("edit", "tool") and ev.get("exit") == 1, False)
    out, code = ev.get("out") or "", ev["exit"]
    fams = primary(ev["cmd"], ev.get("trusted", False))
    if not fams:
        return (False, False)                                  # exploration / scratch / edit scripts: not a product failure
    if re.search(r'"code": ?"(USAGE|GATE_BLOCKED|OUT_OF_ORDER|DRAFT_REJECTED)"', out) and code in (0, 1, 2):
        return (False, False)                                  # a gate doing its job, or help text — not a defect
    if code != 0:
        if code == 1 and (_last_prog(ev["cmd"]) or "").split(" ")[0] in ("grep", "rg", "egrep", "diff", "cmp", "test", "[") and not MARKERS.search(out):
            return (False, False)
        return (True, False)
    if any(f.endswith("autopsy") for f in fams):
        return (False, False)                                  # an autopsy prints errors by design
    if any(EXECUTING.match(f) for f in fams) and MARKERS.search(out):
        if re.search(r"^# fail 0\b", out, re.M) and not re.search(r"^not ok \d+", out, re.M):
            return (False, False)
        return (True, True)
    return (False, False)


# ------------------------------------------------------------------ normalization

def _paths_to(s: str, meta: dict) -> str:
    cwd = meta.get("cwd")
    if cwd:
        s = s.replace(cwd, "<project>")
    s = s.replace(str(Path.home()), "~")
    s = re.sub(r"/tmp/[^\s'\"]+", "<tmp>", s)
    s = re.sub(r"\b[0-9a-f]{12,}\b", "<id>", s)
    return s


def signature(ev: dict) -> str:
    out = (ev.get("out") or "").strip()
    code = ev.get("exit")
    if ev.get("kind") != "cmd":
        line = out.splitlines()[0] if out else f"{ev.get('tool') or 'edit'} failed"
    else:
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        jm = re.search(r'"ok": ?false', out) and re.search(r'"code": ?"(\w+)"(?:[^}]*?"message": ?"([^"]{0,90}))?', out)
        line = (f"{jm.group(1)}: {jm.group(2) or ''}".strip() if jm else None) \
            or next((l for l in lines if SPECIFIC.search(l)), None) or next((l for l in lines if MARKERS.search(l)), None) \
            or next((l for l in lines if FAILWORDS.search(l)), None)
        if not line:
            line = (f"exit {code}: {EXIT_MEANING[code]}" if code in EXIT_MEANING else (lines[-1] if lines else f"exit {code}"))
    line = re.sub(r"(?:[A-Za-z]:)?(?:[\\/][\w.@~+-]+){2,}[\\/]?", "<path>", line)
    line = re.sub(r"\b[0-9a-f]{7,}\b", "<hex>", line)
    line = re.sub(r"\d+(\.\d+)*", "<n>", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line[:160]


def sig_regex(sig: str) -> str:
    rx = re.escape(sig)
    rx = rx.replace(re.escape("<path>"), r"\S+").replace(re.escape("<hex>"), r"[0-9a-f]+").replace(re.escape("<n>"), r"\d+(?:\.\d+)*")
    return rx


def _sid(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


# ------------------------------------------------------------------ analysis

def _owner(ep: dict, meta: dict) -> str:
    first = ep["first_cmd"] or ""
    if ENV_RX.search(ep["signature"]) or (ep["exit"] or 0) >= 124:
        return "environment"
    if meta.get("dev") or any(SKILL_RX.search(f) for f in ep["fix_files"]) or any(GENERATED_RX.search(f) for f in ep["fix_files"]):
        return "skill"                                     # working ON the skill, a fix IN the skill, or in code it generated
    if SKILL_RX.search(first):
        # a deckhand command: a crash is the skill's; a designed refusal (a gate doing its job) is the project's
        if CRASH_RX.search(ep["tail"]) or re.search(r"(skills/deckhand/|\.deckhand/skill/)\S*(tests?|test)/", first):
            return "skill"
        return "project"
    return "project"


def _rung(ep: dict) -> tuple[str, str]:
    o = ep["owner"]
    if o == "skill":
        return "eliminate", "fix it at the source in the skill and add a regression test that fails on the old code"
    if o == "environment":
        return "preflight", "detect the environment condition up front (dh profile doctor) and print the fix before the step"
    if not ep["resolved"]:
        return "gate", "never resolved in this session — make it fail loudly and early (a check before this step), then investigate"
    runs = [s for s in ep["recipe"] if s[0] == "run"]
    edits = [s for s in ep["recipe"] if s[0] == "edit"]
    if runs and not edits and all(SAFE_RX.match(s[1]) for s in runs):
        return "eliminate", "the fix is a safe, repeatable command: run it automatically before this step (dh run --fix replays it)"
    if edits and all(CONFIG_RX.search(s[1]) for s in edits):
        return "preflight", "the fix was a config change: check that setting before this step, fix it deterministically"
    if ep["attempts"] >= 3:
        return "preflight", "it took several attempts: check the precondition before running"
    return "pitfall", "one line where the step is taken: verbatim error → the recipe below (debt: aim higher when it recurs)"


def analyze(events: list, meta: dict, lessons: list | None = None) -> dict:
    lessons = lessons or []
    flags = [is_failure(ev) if ev.get("kind") == "cmd" else (False, False) for ev in events]
    failed_idx = {i for i, (f, _) in enumerate(flags) if f}
    masked_idx = {i for i, (f, m) in enumerate(flags) if f and m}
    # tool errors (an edit that did not apply, a blocked fetch, a missing permission) are listed, not learned from
    tools = {}
    for ev in events:
        if ev.get("kind") in ("edit", "tool") and ev.get("exit") == 1:
            key = (ev.get("tool") or "Edit", signature(ev))
            tools[key] = tools.get(key, 0) + 1
    eps, open_ = [], {}
    for i, ev in enumerate(events):
        if ev.get("kind") != "cmd":
            continue
        if i in failed_idx:
            sig = signature(ev)
            ep = open_.get(sig)
            if ep:
                ep["attempts"] += 1
                ep["fail_idx"].append(i)
                continue
            ep = {"signature": sig, "first": i, "fail_idx": [i], "attempts": 1, "families": primary(ev["cmd"], ev.get("trusted", False)),
                  "first_cmd": ev.get("cmd"), "exit": ev.get("exit"), "masked": i in masked_idx, "resolved": None,
                  "tail": _paths_to((ev.get("out") or "")[-700:], meta)}
            open_[sig] = ep
            eps.append(ep)
        elif ev.get("exit") == 0:
            fam = set(primary(ev["cmd"], ev.get("trusted", False)))
            for sig, ep in list(open_.items()):
                if fam & set(ep["families"]):
                    ep["resolved"] = i
                    del open_[sig]
    for ep in eps:
        last = ep["fail_idx"][-1]
        resolved = ep["resolved"] is not None
        end = ep["resolved"] if resolved else last + 1
        recipe, tried, files = [], [], []
        for k in range(ep["first"] + 1, end):
            ev = events[k]
            steps = []
            if ev.get("kind") == "edit" and ev.get("exit") != 1 and ev.get("file"):
                steps.append(("edit", _paths_to(ev["file"], meta)))
            elif ev.get("kind") == "cmd" and k not in failed_idx and ev.get("exit") == 0:
                steps += [("edit", _paths_to(f, meta)) for f in edits_in(ev["cmd"])]
                fams = [f for f in primary(ev["cmd"]) if not VERIFY.match(f)]
                if fams and not (set(fams) & set(ep["families"])):
                    keep = [x for x in segments(ev["cmd"]) if not _aside(family(x) or "") and not VERIFY.match(family(x) or "")]
                    if keep:
                        steps.append(("run", _paths_to(" && ".join(keep), meta)[:220]))
            for st in steps:
                if st[0] == "edit" and st[1].startswith("<tmp>"):
                    continue                                   # scratch files are not part of any fix
                if st[0] == "edit":
                    files.append(st[1])
                target = recipe if k > last else tried
                if st not in target:
                    target.append(st)
        if len(recipe) > 6:
            # a long window: keep what the failure itself points at, plus the last steps before the proof
            said = ep["tail"].lower()                                  # what the failure itself names
            stem = lambda v: os.path.splitext(os.path.basename(v.split(" ")[0]))[0].lower()  # noqa: E731
            named = [st for st in recipe if len(stem(st[1])) > 3 and stem(st[1]) in said]
            recipe = named + [st for st in recipe[-4:] if st not in named]
            files = [st[1] for st in recipe if st[0] == "edit"]
        t0, t1 = events[ep["first"]].get("ts"), events[min(end, len(events) - 1)].get("ts")
        if t0 and t1 and t1 >= t0:
            ep["minutes"] = round((t1 - t0) / 60, 1)
        ep.update({"recipe": recipe[:10] if resolved else [], "tried": (tried + ([] if resolved else recipe))[:6], "fix_files": sorted(set(files)) if resolved else [],
                   "calls": end - ep["first"], "resolved": resolved,
                   "resolved_by": display(events[ep["resolved"]]["cmd"], meta) if resolved else None,
                   "first_cmd": display(ep["first_cmd"] or "", meta)})
        ep["owner"] = _owner(ep, meta)
        ep["test_in_fix"] = any(TEST_FILE_RX.search(f) for f in ep["fix_files"]) or any(TEST_RUNNER.match(f) for f in ep["families"])
        ep["rung"], ep["why"] = _rung(ep)
        known = [l for l in lessons if _match(l, ep["signature"] + "\n" + ep["tail"])]
        if known:
            ep["known"] = sorted(l["id"] for l in known)
            base = max(RUNG_ORDER.index(l.get("rung", "pitfall")) for l in known)
            if RUNG_ORDER.index(ep["rung"]) <= base:
                ep["rung"] = RUNG_ORDER[min(base + 1, len(RUNG_ORDER) - 1)]
            ep["why"] = f"a lesson existed ({', '.join(ep['known'])}) and it happened again: the {RUNG_ORDER[base]} was not enough — " + ep["why"]
        ep["id"] = "E-" + _sid(ep["signature"])
        del ep["fail_idx"]
    # waste: the same failing command re-run with nothing changed in between
    blind, pending = 0, set()
    for i, ev in enumerate(events):
        if ev.get("kind") == "edit" or (ev.get("kind") == "cmd" and (edits_in(ev["cmd"]) or (i not in failed_idx and ev.get("exit") == 0 and primary(ev["cmd"])))):
            pending = set()
        if ev.get("kind") == "cmd" and i in failed_idx:
            if ev["cmd"] in pending:
                blind += 1
            pending.add(ev["cmd"])
    cmds = [e for e in events if e.get("kind") == "cmd"]
    # the same signature again later in the session is ONE problem that recurred — that is the signal
    merged = {}
    for e in eps:
        m = merged.get(e["id"])
        if not m:
            e["occurrences"] = 1
            merged[e["id"]] = e
            continue
        m["occurrences"] += 1
        m["attempts"] += e["attempts"]
        m["calls"] += e["calls"]
        if not m["resolved"] and e["resolved"]:
            for k in ("recipe", "resolved", "resolved_by", "fix_files", "test_in_fix"):
                m[k] = e[k]
    eps = list(merged.values())
    for e in eps:
        if e["occurrences"] > 1 and RUNG_ORDER.index(e["rung"]) < RUNG_ORDER.index("preflight"):
            e["rung"], e["why"] = "preflight", f"it happened {e['occurrences']} times in one session: check for it before the step — " + e["why"]
    eps.sort(key=lambda e: (-(e["calls"] + 3 * e["attempts"] + 8 * (e["occurrences"] - 1)), e["first"]))
    return {
        "source": meta.get("session"), "events": len(events), "commands": len(cmds), "failures": len(failed_idx),
        "masked_failures": len(masked_idx), "blind_retries": blind, "calls_in_failure_windows": sum(e["calls"] for e in eps),
        "tool_errors": [{"tool": t, "signature": sg, "count": n} for (t, sg), n in sorted(tools.items(), key=lambda x: (-x[1], x[0]))][:12],
        "episodes": [{k: e[k] for k in ("id", "owner", "rung", "why", "signature", "first_cmd", "exit", "masked", "attempts", "occurrences", "calls",
                                        "resolved", "resolved_by", "recipe", "tried", "fix_files", "test_in_fix", "tail", "first")}
                     | ({"known": e["known"]} if e.get("known") else {}) | ({"minutes": e["minutes"]} if e.get("minutes") is not None else {})
                     for e in eps],
        "playbooks": [] if meta.get("dev") else playbooks(events, failed_idx, meta),
    }


def _match(lesson: dict, text: str) -> bool:
    try:
        return bool(re.search(lesson.get("signature") or "(?!x)x", text, re.I | re.M))
    except re.error:
        return False


def playbooks(events: list, failed_idx: set, meta: dict) -> list:
    """Successful phase runs: the state-changing commands between two `dh phase done` successes."""
    out, steps = [], []
    for i, ev in enumerate(events):
        if ev.get("kind") != "cmd" or ev.get("exit") != 0 or i in failed_idx or _scratch(ev["cmd"]):
            continue
        m = re.search(r"(\bdh|dh\.py)\b.*\bphase\s+done\s+(\w+)", ev["cmd"])
        if m:
            if steps:
                out.append({"phase": m.group(2), "steps": steps[:25]})
            steps = []
            continue
        keep = [x for x in segments(ev["cmd"]) if not _aside(family(x, ev.get("trusted", False)) or "") and not VERIFY.match(family(x, ev.get("trusted", False)) or "")]
        if keep:
            st = _paths_to(" && ".join(keep), meta)[:200]
            if not steps or steps[-1] != st:
                steps.append(st)
    return out


# ------------------------------------------------------------------ report

def render(rep: dict, name: str) -> str:
    eps = rep["episodes"]
    L = [f"# Autopsy — {name}", "",
         f"{rep['commands']} commands · {rep['failures']} failures ({rep['masked_failures']} hidden behind a pipe) · "
         f"{len(eps)} episodes · {rep['calls_in_failure_windows']} tool calls spent inside failure windows · {rep['blind_retries']} blind retries", ""]
    if not eps:
        L += ["Nothing to learn from: no failure outside scratch scripts.", ""]
    for e in eps[:12]:
        state = (f"resolved after {e['attempts']} attempt(s), {e['calls']} calls" if e["resolved"] else f"UNRESOLVED ({e['attempts']} attempt(s))") \
            + (f", **happened {e['occurrences']}×**" if e.get("occurrences", 1) > 1 else "")
        L += [f"## {e['id']} · {e['owner']} · **{e['rung']}** · {state}", "",
              f"- signature: `{e['signature']}`" + (" *(exit 0 — found in the output)*" if e["masked"] else ""),
              f"- first failing command: `{(e['first_cmd'] or '')[:160]}`"]
        if e.get("known"):
            L.append(f"- known lesson(s) {', '.join(e['known'])} did not prevent it")
        if e["tried"]:
            L.append("- tried first (did not fix it): " + "; ".join(f"{k} `{v[:90]}`" for k, v in e["tried"][:4]))
        if e["recipe"]:
            L.append("- **what fixed it:** " + " → ".join(f"{k} `{v[:110]}`" for k, v in e["recipe"]))
        if e["resolved_by"]:
            L.append(f"- proof: `{e['resolved_by'][:140]}` succeeded")
        if e["owner"] == "skill":
            L.append("- regression test: " + ("yes (a test caught it, or one was edited in the fix)" if e["test_in_fix"] else "**MISSING** — a fix without a test is not a fix"))
        L += [f"- next: {e['why']}", ""]
    if len(eps) > 12:
        L += [f"…and {len(eps) - 12} cheaper episodes in the JSON report.", ""]
    if rep.get("tool_errors"):
        L += ["## Tool errors (agent mechanics / environment — not learned from)", ""]
        L += [f"- {t['tool']} ×{t['count']}: `{t['signature'][:110]}`" for t in rep["tool_errors"]]
        L.append("")
    if rep["playbooks"]:
        L += ["## Workflows that worked", ""]
        for p in rep["playbooks"]:
            L.append(f"- phase **{p['phase']}**: " + " → ".join(f"`{s[:70]}`" for s in p["steps"][:10]))
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def autopsy(root: Path | None, source: str | None = None, latest: bool = False, apply: bool = False, session: str | None = None) -> dict:
    root = Path(root) if root else Path.cwd()
    if source:
        path = Path(source).expanduser()
    elif latest:
        path = latest_source(root)
    else:
        path = root / ".deckhand" / "runs.jsonl"
        if not path.exists():
            path = latest_source(root)
    if not path.exists():
        raise DhError("NO_SOURCE", f"{path} does not exist")
    kind = detect(path)
    events, meta = load(path, kind, session, root)
    meta["dev"] = bool(meta.get("cwd") and (Path(meta["cwd"]) / "skills" / "deckhand" / "SKILL.md").exists())
    from . import learn as LE
    rep = RD.scrub_obj(analyze(events, meta, LE.all_lessons(root)))
    rep["kind"] = kind
    rid = "A-" + hashlib.sha1(path.read_bytes() + (meta.get("session") or "").encode()).hexdigest()[:10]
    out = root / ".deckhand" / "autopsy"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / f"{rid}.json", rep)
    (out / f"{rid}.md").write_text(render(rep, path.name), encoding="utf-8")
    res = {"id": rid, "source": str(path), "kind": kind, "report": str(out / f"{rid}.md"),
           "summary": {k: rep[k] for k in ("commands", "failures", "masked_failures", "blind_retries", "calls_in_failure_windows")},
           "episodes": [{k: e[k] for k in ("id", "owner", "rung", "attempts", "resolved", "signature")} for e in rep["episodes"]][:12]}
    if apply:
        res["applied"] = apply_report(root, rep, rid)
        write_json(out / "applied.json", {"id": rid, "at": now()})
    else:
        res["next"] = "read the report; `dh autopsy … --apply` writes the lessons (with recipes), skill proposals and playbooks"
    return res


def apply_report(root: Path, rep: dict, rid: str) -> dict:
    from . import learn as LE
    from . import state as STATE
    s = STATE.load(root, required=False) if root else None
    phase = STATE.current(s)["id"] if s else "build"
    lessons, proposals = [], []
    done = _applied_keys()
    fresh = set()
    for e in rep["episodes"]:
        if e["owner"] == "skill":
            proposals.append(_proposal(e, rid))
            continue
        if not e["resolved"] or not e["recipe"]:
            continue
        ekey = _sid(rid + "\n" + e["signature"] + "\n" + json.dumps(e["recipe"]))        # the evidence, not the clock (C10)
        if ekey in done:
            lessons.append({"episode": e["id"], "skipped": "already applied from this session"})
            continue
        fresh.add(ekey)
        runs = [v for k, v in e["recipe"] if k == "run"]
        auto = bool(runs) and not any(k == "edit" for k, _ in e["recipe"]) and all(SAFE_RX.match(r) and "***" not in r for r in runs)
        fix = " → ".join(f"{k} {v}" for k, v in e["recipe"])
        r = LE.add(root, phase, e["signature"], f"{e['owner']}: {e['why']}", fix, signature=sig_regex(e["signature"]),
                   command=runs[-1] if runs else None, rung=e["rung"], scope="global",
                   extra={"recipe": e["recipe"], "auto": auto, "source": rid})
        lessons.append({"episode": e["id"], **r})
    books = []
    for p in rep["playbooks"]:
        key = _sid(p["phase"] + "\n" + "\n".join(p["steps"]))
        ekey = _sid(rid + "\n" + key)
        if ekey in done:
            books.append({"phase": p["phase"], "key": key, "skipped": "already applied from this session"})
            continue
        fresh.add(ekey)
        target = home() / "playbooks.jsonl"
        rows = read_jsonl(target)
        hit = next((x for x in rows if x.get("key") == key), None)
        if hit:
            hit["seen"] = hit.get("seen", 1) + 1
            hit["last_seen"] = now()
            target.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        else:
            append_jsonl(target, {"key": key, "phase": p["phase"], "steps": p["steps"], "seen": 1, "source": rid, "last_seen": now()})
        books.append({"phase": p["phase"], "key": key})
    for k in sorted(fresh):
        append_jsonl(home() / "autopsy" / "applied.jsonl", {"key": k, "at": now()})
    return {"lessons": lessons, "proposals": proposals, "playbooks": books}


def _applied_keys() -> set:
    return {r.get("key") for r in read_jsonl(home() / "autopsy" / "applied.jsonl")}


def _proposal(e: dict, rid: str) -> str:
    d = home() / "autopsy" / "proposals"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{e['id']}.md"
    cl = RD.clean_text                                                    # a proposal may travel: no personal paths, no secrets (C11)
    body = [f"# Skill fix proposal {e['id']} (from {rid})", "",
            f"**Rung:** {e['rung']} — {cl(e['why'])}", "",
            "## Repro", "", "```", cl((e["first_cmd"] or "")[:400]), "```", "",
            f"exit {e['exit']}" + (" (hidden behind a pipe)" if e["masked"] else ""), "", "```", cl(e["tail"][-600:]), "```", "",
            "## What fixed it in the session", ""]
    body += [f"- {k}: `{cl(v)}`" for k, v in e["recipe"]] or ["- (not resolved in the session)"]
    body += ["", "## Done means", "",
             "- the fix lives in the skill's code/templates (not in prose)",
             "- a regression test fails on the old code and passes on the new: " + ("present in the fix ✓" if e["test_in_fix"] else "**missing — write it**"),
             "- CHANGELOG entry; `dh autopsy` on a replay of this session no longer reports it", ""]
    p.write_text("\n".join(body), encoding="utf-8")
    return str(p)
