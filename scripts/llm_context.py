#!/usr/bin/env python3
"""llm_context.py — builds LLM_CONTEXT.md: this whole repo, compressed for a model that has no memory.

  python3 scripts/llm_context.py            regenerate LLM_CONTEXT.md from the working tree
  python3 scripts/llm_context.py --check    exit 1 when LLM_CONTEXT.md is stale or a curated anchor broke
  python3 scripts/llm_context.py --index    regenerate from the git index (what .githooks/pre-commit runs)

Two inputs. (1) The code: every [gen] section is extracted from the files themselves (tree, commands,
modules with exact line numbers, error codes, env vars, data shapes, docs outline, tests, CI), so it cannot
drift. (2) scripts/llm_context.core.md: the curated model (architecture, invariants, flows, routing,
gotchas). The core points at code through anchors, resolved to path:line at build time:
  [[path]]  [[path#symbol]]  [[dh:subcommand]]  [[tryon:command]]  [[api:name]]  [[!ERROR_CODE]]
An anchor that no longer resolves fails the build, so the curated half cannot silently rot either.
Deterministic (same tree -> same bytes), stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = "LLM_CONTEXT.md"
CORE = "scripts/llm_context.core.md"
SKILL = "skills/deckhand/"
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".pdf", ".zip", ".db", ".sqlite"}
CODE_EXT = {".py", ".mjs", ".cjs", ".js"}
# (prefix, what it is) — listed as one line in the map, never parsed
COLLAPSE = [
    (SKILL + "tryon/test/fixtures/registry/", "recorded registry HTTP responses, replayed offline via DH_FIXTURES"),
    (SKILL + "data/pool/", "measured detail of each pool row (dh pool show NAME); rows are in data/pool.json"),
    (SKILL + "tryon/vendor/", "vendored @babel/parser (MIT) — never edit, never parse"),
]
CAP = 110          # max chars for a one-line summary


# ---------------------------------------------------------------- input

def _git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, input=data, capture_output=True, check=True).stdout


def load_tree(index: bool = False) -> dict:
    """{repo-relative posix path: text or None (binary)} — the git index, or what `git add -A` would commit."""
    raw: dict = {}
    try:
        if index:
            entries = []
            for e in _git("ls-files", "-s", "-z").split(b"\0"):
                if not e:
                    continue
                meta, path = e.split(b"\t", 1)
                mode, sha, stage = meta.split()
                if stage == b"0" and mode != b"160000":
                    entries.append((path.decode("utf-8"), sha.decode()))
            blob = _git("cat-file", "--batch", data=("\n".join(s for _, s in entries) + "\n").encode())
            pos = 0
            for path, _sha in entries:
                nl = blob.index(b"\n", pos)
                size = int(blob[pos:nl].split()[2])
                raw[path] = blob[nl + 1: nl + 1 + size]
                pos = nl + 1 + size + 1
        else:
            for p in _git("ls-files", "-co", "--exclude-standard", "-z").split(b"\0"):
                if p and (ROOT / p.decode("utf-8")).is_file():
                    raw[p.decode("utf-8")] = (ROOT / p.decode("utf-8")).read_bytes()
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", "node_modules", "__pycache__", ".pytest_cache"}
        for dp, dns, fns in os.walk(ROOT):
            # a run's own state (<root>/.deckhand) is local; a `.deckhand` folder deeper down is content that ships
            # (the playground snapshot's brief and plan), and the git listing above already counts it
            dns[:] = [d for d in dns if d not in skip and not (d == ".deckhand" and Path(dp) == ROOT)]
            for f in fns:
                full = Path(dp) / f
                raw[full.relative_to(ROOT).as_posix()] = full.read_bytes()
    raw.pop(OUT, None)
    return {path: decode(path, raw[path]) for path in sorted(raw)}


def decode(path: str, b: bytes) -> str | None:
    """Text with LF line ends (a Windows checkout gives the same map), or None for a binary file."""
    if Path(path).suffix.lower() in BINARY_EXT or b"\0" in b[:8192]:
        return None
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


def short(path: str) -> str:
    """Display path: skill files relative to skills/deckhand/, everything else relative to the repo root."""
    return path[len(SKILL):] if path.startswith(SKILL) else path


def full(path: str, files: dict) -> str | None:
    for cand in (path, SKILL + path):
        if cand in files or any(f.startswith(cand.rstrip("/") + "/") for f in files):
            return cand
    return None


def one(s: str | None, cap: int = CAP) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s if len(s) <= cap else s[: cap - 1].rstrip() + "…"


def collapsed(path: str):
    for pre, what in COLLAPSE:
        if path.startswith(pre):
            return pre, what
    return None


# ---------------------------------------------------------------- per-language analysis

def _default(node) -> str:
    if isinstance(node, ast.Constant) and len(repr(node.value)) <= 12:
        return repr(node.value)
    return "…"


def py_sig(fn) -> str:
    a = fn.args
    pos = a.posonlyargs + a.args
    defs = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    out = [p.arg + ("" if d is None else "=" + _default(d)) for p, d in zip(pos, defs)]
    if a.vararg:
        out.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        out.append("*")
    out += [k.arg + ("" if d is None else "=" + _default(d)) for k, d in zip(a.kwonlyargs, a.kw_defaults)]
    if a.kwarg:
        out.append("**" + a.kwarg.arg)
    return ", ".join(out)


def py_info(path: str, text: str) -> dict:
    info = {"lang": "py", "doc": "", "api": [], "internal": [], "consts": [], "symbols": {}, "deps": set(), "error": None}
    try:
        t = ast.parse(text)
    except SyntaxError as e:
        info["error"] = f"SyntaxError L{e.lineno}"
        return info
    info["doc"] = ast.get_docstring(t) or ""
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            row = {"name": n.name, "line": n.lineno,
                   "sig": "class" if isinstance(n, ast.ClassDef) else py_sig(n),
                   "doc": (ast.get_docstring(n) or "").split("\n")[0]}
            (info["internal"] if n.name.startswith("_") else info["api"]).append(row)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for tg in targets:
                for name in ([tg] if isinstance(tg, ast.Name) else getattr(tg, "elts", [])):
                    if isinstance(name, ast.Name) and name.id.isupper():
                        info["consts"].append({"name": name.id, "line": n.lineno})
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            info["symbols"].setdefault(n.name, n.lineno)
            if isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        info["symbols"].setdefault(f"{n.name}.{m.name}", m.lineno)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)) and n.col_offset == 0:
            for tg in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if isinstance(tg, ast.Name):
                    info["symbols"].setdefault(tg.id, n.lineno)
        elif isinstance(n, ast.ImportFrom) and n.level >= 1:
            base = Path(path).parent
            for _ in range(n.level - 1):
                base = base.parent
            if n.module:
                info["deps"].add((base / n.module.replace(".", "/")).as_posix() + ".py")
            else:
                for al in n.names:
                    info["deps"].add((base / al.name).as_posix() + ".py")
    return info


JS_HEADER = re.compile(r"\A(?:#![^\n]*\n)?(?:\s*'use strict';?\s*\n)?\s*/\*\*?(.*?)\*/", re.S)
JS_DEF = [
    (re.compile(r"^export\s+default\s+(?:async\s+)?function\s*\*?\s*(\w*)\s*\("), "api"),
    (re.compile(r"^export\s+(?:async\s+)?function\s*\*?\s*(\w+)\s*\("), "api"),
    (re.compile(r"^export\s+class\s+(\w+)"), "api"),
    (re.compile(r"^export\s+(?:const|let)\s+(\w+)\s*="), "api"),
    (re.compile(r"^(?P<ind>\s*)(?:async\s+)?function\s*\*?\s*(\w+)\s*\("), "internal"),
    (re.compile(r"^(?P<ind>\s*)(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"), "internal"),
    (re.compile(r"^(?:const|let)\s+([A-Z][A-Z0-9_]+)\s*="), "const"),
]
JS_FN_RHS = re.compile(r"=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|\w+\s*=>)")
JS_ANY_DEF = re.compile(r"(?:^|[\s;(])(?:async\s+)?function\s*\*?\s*(\w+)\s*\(|(?:^|[\s;])(?:const|let|var)\s+(\w+)\s*=|(?:^|\s)class\s+(\w+)")
JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(\s*|\brequire\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]""")


def _params(lines: list, i: int, start: int) -> str:
    """The parameter text of a definition whose '(' is at lines[i][start:] (spans up to 4 lines)."""
    buf, depth = "", 0
    for j in range(i, min(i + 4, len(lines))):
        seg = lines[j][start:] if j == i else lines[j]
        for ch in seg:
            if ch == "(":
                depth += 1
                if depth == 1:
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return one(buf, 90)
            if depth >= 1:
                buf += ch
        buf += " "
    return one(buf, 90)


def _js_doc(lines: list, i: int) -> str:
    """The comment right above a definition (JSDoc or // lines), else a trailing // on its line."""
    j, got = i - 1, []
    while j >= 0 and re.match(r"^\s*(//|\*|/\*\*|\*/)", lines[j]):
        got.insert(0, re.sub(r"^\s*(/\*\*|\*/|\*|//)\s?", "", lines[j]).strip())
        j -= 1
    text = " ".join(x for x in got if x)
    if not text:
        m = re.search(r"\s//\s*(.+)$", lines[i])
        text = m.group(1) if m else ""
    text = re.sub(r"\s*\*/\s*$", "", text)
    return re.split(r"(?<=\.)\s", text, maxsplit=1)[0] if text else ""


def js_info(path: str, text: str) -> dict:
    info = {"lang": "js", "doc": "", "api": [], "internal": [], "consts": [], "symbols": {}, "deps": set(), "error": None}
    m = JS_HEADER.match(text)
    if m:
        info["doc"] = "\n".join(re.sub(r"^\s*\* ?", "", ln).rstrip() for ln in m.group(1).split("\n")).strip()
    else:
        head = []
        for ln in text.split("\n")[:12]:
            if ln.startswith("#!"):
                continue
            if not ln.startswith("//"):
                break
            head.append(ln[2:].strip())
        info["doc"] = "\n".join(head)
    lines = text.split("\n")
    seen = set()
    # an IIFE file (the overlay) has no top-level definitions: its functions sit one indent level in
    top = 0 if any(re.match(r"^(?:export\s+)?(?:async\s+)?function\b", ln) for ln in lines) else 2
    for i, ln in enumerate(lines):
        for rx, kind in JS_DEF:
            mm = rx.match(ln)
            if not mm:
                continue
            if "ind" in rx.groupindex and len(mm.group("ind")) != top:
                break
            name = mm.group(mm.lastindex if "ind" in rx.groupindex else 1) or "default"
            if name in seen:
                break
            seen.add(name)
            row = {"name": name, "line": i + 1, "doc": _js_doc(lines, i)}
            stripped = ln.lstrip()
            if stripped.startswith(("export class", "class")):
                row["sig"] = "class"
            elif kind == "const":
                pass
            elif re.match(r"^(export\s+)?(default\s+)?(async\s+)?function\b", stripped):
                row["sig"] = _params(lines, i, ln.find("(", mm.end() - 1))
            elif JS_FN_RHS.search(ln):
                eq = JS_FN_RHS.search(ln)
                p = ln.find("(", eq.start())
                row["sig"] = _params(lines, i, p) if p != -1 and p < eq.end() else re.search(r"(\w+)\s*=>", ln[eq.start():]).group(1)
            {"api": info["api"], "internal": info["internal"], "const": info["consts"]}[kind].append(row)
            break
        for mm in JS_ANY_DEF.finditer(ln):
            name = mm.group(1) or mm.group(2) or mm.group(3)
            if name:
                info["symbols"].setdefault(name, i + 1)
        me = re.match(r"^module\.exports\s*=\s*\{([^}]*)\}", ln)
        if me:
            names = {x.split(":")[0].strip() for x in me.group(1).split(",") if x.strip()}
            info["internal"], moved = [r for r in info["internal"] if r["name"] not in names], [r for r in info["internal"] if r["name"] in names]
            info["api"] += moved
        me = re.match(r"^module\.exports\s*=\s*function\s+(\w+)\s*\(", ln)
        if me:
            info["api"].append({"name": me.group(1), "line": i + 1, "sig": _params(lines, i, ln.find("(")), "doc": _js_doc(lines, i)})
            info["symbols"].setdefault(me.group(1), i + 1)
    # anchors prefer the top-level definition over a same-named local further up the file
    for r in info["api"] + info["internal"] + info["consts"]:
        info["symbols"][r["name"]] = r["line"]
    for mm in JS_IMPORT.finditer(text):
        info["deps"].add(os.path.normpath(str(Path(path).parent / mm.group(1))).replace("\\", "/"))
    info["api"].sort(key=lambda r: r["line"])
    return info


def md_info(text: str) -> dict:
    heads, fence = [], False
    for i, ln in enumerate(text.split("\n"), 1):
        if ln.startswith("```"):
            fence = not fence
        elif not fence:
            m = re.match(r"^(#{1,3})\s+(.+?)\s*#*\s*$", ln)
            if m:
                heads.append((len(m.group(1)), m.group(2), i))
    return {"heads": heads}


def analyze(files: dict) -> dict:
    mods = {}
    for path, text in files.items():
        if text is None or collapsed(path):
            continue
        ext = Path(path).suffix
        if ext == ".py":
            mods[path] = py_info(path, text)
        elif ext in (".mjs", ".cjs", ".js"):
            mods[path] = js_info(path, text)
        elif ext == ".md":
            mods[path] = {"lang": "md", **md_info(text)}
    for info in mods.values():
        if "deps" in info:
            info["deps"] = sorted(d for d in info["deps"] if d in files)
    return mods


def purpose(path: str, text: str | None, info: dict | None) -> str:
    if text is None:
        return "(binary)"
    if info and info.get("lang") in ("py", "js"):
        first = re.split(r"\n\s*\n", info["doc"].strip(), maxsplit=1)[0] if info["doc"] else ""
        return one(first)
    if info and info.get("lang") == "md":
        h1 = [h for lvl, h, _ in info["heads"] if lvl == 1]
        html = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
        return one(h1[0] if h1 else re.sub(r"<[^>]+>", "", html.group(1)) if html else info["heads"][0][1] if info["heads"] else "")
    ext = Path(path).suffix
    if ext == ".json":
        try:
            d = json.loads(text)
        except ValueError:
            return "json (unparsable)"
        if isinstance(d, dict):
            about = d.get("_about") or d.get("note") or d.get("policy")
            return one(("keys: " + ", ".join(list(d)[:8])) + (f" — {about}" if isinstance(about, str) else ""))
        return f"json list[{len(d)}]"
    block = []
    for ln in text.split("\n")[:12]:
        m = re.match(r"^\s*(#|//|--|::|rem|REM)(?!!)\s?(.*)$", ln)
        if not m:
            if block:
                break
            continue
        if not m.group(2).strip():
            if block:
                break
            continue
        block.append(m.group(2).strip())
    return one(" ".join(block))


# ---------------------------------------------------------------- commands

def const_values(files: dict, pkg: str, node) -> list | None:
    """Values of MODULE.NAME for an `from . import module as ALIAS` constant (literal, or [x["k"] for x in LITERAL])."""
    cli = ast.parse(files[pkg + "cli.py"])
    mod = next((n.module or a.name for n in cli.body if isinstance(n, ast.ImportFrom) for a in n.names
                if (a.asname or a.name) == getattr(node.value, "id", None)), None)
    src = files.get(pkg + f"{mod}.py") if mod else None
    if not src:
        return None
    assigns = {t.id: n.value for n in ast.parse(src).body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    v = assigns.get(node.attr)
    try:
        return list(ast.literal_eval(v))
    except (ValueError, TypeError, SyntaxError):
        pass
    if isinstance(v, ast.ListComp) and isinstance(v.elt, ast.Subscript) and isinstance(v.generators[0].iter, ast.Name):
        try:
            rows = ast.literal_eval(assigns[v.generators[0].iter.id])
            return [r[ast.literal_eval(v.elt.slice)] for r in rows]
        except (ValueError, TypeError, SyntaxError, KeyError):
            return None
    return None


def dh_commands(files: dict, mods: dict) -> tuple:
    """(commands, handlers) from dhlib/cli.py: argparse structure + the dispatch branch of each command."""
    path = SKILL + "dhlib/cli.py"
    if not files.get(path):
        return [], {}
    t = ast.parse(files[path])
    fns = {n.name: n for n in t.body if isinstance(n, ast.FunctionDef)}
    cmds: dict = {}
    order: list = []
    cur = None

    def lit(n):
        return n.value if isinstance(n, ast.Constant) else None

    class Unroll(ast.NodeTransformer):                     # `for f in ("--why", …): p.add_argument(f, …)` → one call per flag
        def visit_For(self, node):
            if isinstance(node.target, ast.Name) and isinstance(node.iter, (ast.Tuple, ast.List)) and all(isinstance(e, ast.Constant) for e in node.iter.elts):
                out = []
                for e in node.iter.elts:
                    for b in node.body:
                        c = __import__("copy").deepcopy(b)
                        for n in ast.walk(c):
                            for f, v in ast.iter_fields(n):
                                if isinstance(v, ast.Name) and v.id == node.target.id:
                                    setattr(n, f, ast.Constant(e.value))
                                elif isinstance(v, list):
                                    v[:] = [ast.Constant(e.value) if isinstance(x, ast.Name) and x.id == node.target.id else x for x in v]
                        out.append(c)
                return out
            return node

    bp = Unroll().visit(fns["build_parser"])
    groups: dict = {}                                       # parent parsers (`parents=[where]`): their flags join each command
    for st in ast.walk(bp):
        if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute) \
                and st.value.func.attr == "add_mutually_exclusive_group" and isinstance(st.value.func.value, ast.Name):
            groups[st.targets[0].id] = st.value.func.value.id
    shared: dict = {}
    for st in ast.walk(bp):
        if isinstance(st, ast.Call) and isinstance(st.func, ast.Attribute) and st.func.attr == "add_argument" \
                and isinstance(st.func.value, ast.Name) and st.func.value.id in groups and st.args and isinstance(lit(st.args[0]), str):
            shared.setdefault(groups[st.func.value.id], []).append(lit(st.args[0]))
    for st in ast.walk(bp):
        call = st.value if isinstance(st, (ast.Assign, ast.Expr)) and isinstance(getattr(st, "value", None), ast.Call) else None
        if not call or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr == "add_parser" and call.args and isinstance(lit(call.args[0]), str):
            cur = lit(call.args[0])
            cmds[cur] = {"args": [], "help": next((lit(k.value) for k in call.keywords if k.arg == "help"), None), "line": st.lineno}
            for k in call.keywords:
                if k.arg == "parents" and isinstance(k.value, ast.List):
                    for e in k.value.elts:
                        if isinstance(e, ast.Name) and shared.get(e.id):
                            cmds[cur]["args"].append("[" + "|".join(shared[e.id]) + "]")
            order.append(cur)
            if isinstance(st, ast.Expr):
                cur = None
        elif call.func.attr == "add_argument" and cur and isinstance(call.func.value, ast.Name) and call.func.value.id == "p":
            name = lit(call.args[0]) if call.args else None
            kw = {k.arg: k.value for k in call.keywords}
            if name is None or kw.get("default") is not None and isinstance(kw["default"], ast.Attribute):
                continue
            choices = [lit(e) for e in getattr(kw.get("choices"), "elts", [])] if isinstance(kw.get("choices"), (ast.List, ast.Tuple)) else None
            if isinstance(kw.get("choices"), ast.Attribute):
                choices = const_values(files, SKILL + "dhlib/", kw["choices"]) or [kw["choices"].attr]
            nargs = kw.get("nargs")
            nargs = lit(nargs) if isinstance(nargs, ast.Constant) else ("..." if nargs is not None else None)
            dflt = lit(kw["default"]) if "default" in kw else None
            action = lit(kw["action"]) if "action" in kw else None
            req = lit(kw["required"]) if "required" in kw else False
            hlp = lit(kw["help"]) if "help" in kw else None
            if name.startswith("--"):
                meta = "|".join(map(str, choices)) if choices else name[2:].upper().replace("-", "_")
                s = name if action == "store_true" else f"{name} {meta}" + (f"={dflt}" if dflt not in (None, "") else "")
                s = s if req else f"[{s}]"
            else:
                meta = "{" + "|".join(map(str, choices)) + "}" if choices else name.upper()
                s = {"?": f"[{meta}]", "*": f"[{meta}…]", "...": f"[-- {name}…]"}.get(nargs, meta)
            cmds[cur]["args"].append(s + (f"  # {hlp}" if hlp and hlp != "==SUPPRESS==" else ""))
    # dispatch: which module functions each command reaches
    alias = {}
    for n in t.body:
        if isinstance(n, ast.ImportFrom) and n.level == 1:
            for al in n.names:
                alias[al.asname or al.name] = (n.module or al.name, None if n.module else al.name)
    for m in ast.walk(fns["dispatch"]):                    # lazy imports: `from . import pool as POOL` inside branches
        if isinstance(m, ast.ImportFrom) and m.level == 1:
            for al in m.names:
                alias[al.asname or al.name] = (m.module or al.name, None if m.module else al.name)
    handlers: dict = {}
    for n in ast.walk(fns["dispatch"]):
        if not isinstance(n, ast.If) or not isinstance(n.test, ast.Compare):
            continue
        left = n.test.left
        if not (isinstance(left, ast.Name) and left.id == "c"):
            continue
        comp = n.test.comparators[0]
        names = [lit(comp)] if isinstance(comp, ast.Constant) else [lit(e) for e in getattr(comp, "elts", [])]
        local = dict(alias)
        calls = []
        for m in ast.walk(n):
            if isinstance(m, ast.ImportFrom) and m.level == 1:
                for al in m.names:
                    local[al.asname or al.name] = (m.module or al.name, None if m.module else al.name)
        for m in ast.walk(n):
            if isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute) and isinstance(m.func.value, ast.Name) and m.func.value.id in local:
                mod = local[m.func.value.id]
                modname = mod[1] or mod[0]
                calls.append((modname, m.func.attr))
            elif isinstance(m, ast.Call) and isinstance(m.func, ast.Name) and m.func.id in fns:
                calls.append(("cli", m.func.id))
        for nm in names:
            if nm and (nm not in handlers or len(names) < handlers[nm]["width"]):
                handlers[nm] = {"line": n.lineno, "end": n.end_lineno, "calls": sorted(set(calls), key=calls.index), "width": len(names)}
    for nm, h in handlers.items():
        if h["width"] > 1:
            claimed = {c for oh in handlers.values() if oh["width"] == 1 and h["line"] < oh["line"] <= h["end"] for c in oh["calls"]}
            own = [c for c in h["calls"] if c not in claimed]
            h["calls"] = own or h["calls"]
    return [(c, cmds[c]) for c in order], handlers


def js_cases(text: str, fn_start: str) -> list:
    """[(case, line, body)] for the switch inside the function whose definition line contains fn_start."""
    lines = text.split("\n")
    try:
        start = next(i for i, ln in enumerate(lines) if fn_start in ln)
    except StopIteration:
        return []
    out = []
    ind = None
    for i in range(start, len(lines)):
        m = re.match(r"^(\s*)case '([\w-]+)':", lines[i])
        if m and (ind is None or len(m.group(1)) == ind):
            ind = len(m.group(1))
            out.append([m.group(2), i + 1, lines[i]])
        elif out and (re.match(r"^(\s*)default:", lines[i]) and len(re.match(r"^(\s*)", lines[i]).group(1)) == ind):
            break
        elif out:
            out[-1][2] += "\n" + lines[i]
        if out and re.match(r"^\S", lines[i]) and i > start:
            break
    return out


def js_imports(path: str, text: str) -> dict:
    """local name -> (module path, exported name or '*')."""
    out = {}
    for m in re.finditer(r"import\s+(\*\s+as\s+(\w+)|\{([^}]*)\}|(\w+))\s+from\s+'(\.{1,2}/[^']+)'", text):
        mod = os.path.normpath(str(Path(path).parent / m.group(5))).replace("\\", "/")
        if m.group(2):
            out[m.group(2)] = (mod, "*")
        elif m.group(3):
            for part in m.group(3).split(","):
                part = part.strip()
                if part:
                    a, _, b = part.partition(" as ")
                    out[(b or a).strip()] = (mod, a.strip())
        elif m.group(4):
            out[m.group(4)] = (mod, "default")
    return out


def js_calls(body: str, imports: dict) -> list:
    calls = []
    for m in re.finditer(r"\b(\w+)\.(\w+)\s*\(|\b(\w+)\s*\(", body):
        if m.group(1) and m.group(1) in imports and imports[m.group(1)][1] == "*":
            calls.append((imports[m.group(1)][0], m.group(2)))
        elif m.group(3) and m.group(3) in imports and imports[m.group(3)][1] != "*":
            calls.append((imports[m.group(3)][0], imports[m.group(3)][1]))
    return sorted(set(calls), key=calls.index)


def tryon_commands(files: dict) -> list:
    path = SKILL + "tryon/cli.mjs"
    text = files.get(path) or ""
    usage = {}
    for ln in text.split("\n")[:40]:
        m = re.match(r"^\s*\*\s+node tryon/cli\.mjs\s+([\w-]+)\s*(.*)$", ln)
        if m:
            usage.setdefault(m.group(1), one(m.group(2), 150))
    imports = js_imports(path, text)
    return [(c, line, usage.get(c, ""), js_calls(body, imports)) for c, line, body in js_cases(text, "async function main")]


def api_routes(files: dict) -> list:
    path = SKILL + "tryon/server.mjs"
    text = files.get(path) or ""
    imports = js_imports(path, text)
    return [(c, line, js_calls(body, imports)) for c, line, body in js_cases(text, "async function api(")]


# ---------------------------------------------------------------- indexes

ERR_PATTERNS = [
    re.compile(r"""DhError\(\s*["']([A-Z][A-Z0-9_]+)["']\s*(?:,\s*(f?["'][^"'\n]*))?"""),
    re.compile(r"""TryonError\(\s*'([A-Z][A-Z0-9_]+)'\s*(?:,\s*([`'][^`'\n]*))?"""),
    re.compile(r"""\bcode:\s*'([A-Z][A-Z0-9_]{2,})'(?:[^}\n]*?(?:message|why|hint):\s*([`'][^`'\n]*))?"""),
    re.compile(r"""["']code["']:\s*["']([A-Z][A-Z0-9_]{2,})["']"""),
]
ENV_PATTERNS = [
    re.compile(r"""os\.environ\.get\(\s*["'](\w+)["']"""), re.compile(r"""os\.environ\[\s*["'](\w+)["']\s*\]"""),
    re.compile(r"""os\.getenv\(\s*["'](\w+)["']"""), re.compile(r"""process\.env\.(\w+)"""),
    re.compile(r"""process\.env\[\s*['"](\w+)['"]\s*\]"""),
]


def is_test(path: str) -> bool:
    return bool(re.search(r"(^|/)(tests?|test)/|(^|/)test_[^/]+\.py$|\.test\.mjs$", path))


def scan_index(files: dict, patterns: list, code_only=True) -> dict:
    out: dict = {}
    for path, text in files.items():
        if text is None or collapsed(path) or Path(path).suffix not in CODE_EXT or is_test(path) or path.startswith("scripts/llm_context"):
            continue
        for i, ln in enumerate(text.split("\n"), 1):
            for rx in patterns:
                for m in rx.finditer(ln):
                    msg = (m.group(2) if m.lastindex and m.lastindex >= 2 else None) or ""
                    msg = re.sub(r"^f?[\"'`]", "", msg)
                    out.setdefault(m.group(1), []).append((short(path), i, one(msg, 80)))
    return out


def shape(x, depth: int = 0) -> str:
    if isinstance(x, dict):
        if depth >= 2:
            return "{…}"
        return "{" + ", ".join(f"{k}:{shape(v, depth + 1)}" for k, v in list(x.items())[:16]) + (", …" if len(x) > 16 else "") + "}"
    if isinstance(x, list):
        return f"[{len(x)}×{shape(x[0], depth + 1) if x else ''}]"
    return {str: "s", int: "n", float: "n", bool: "b", type(None): "null"}.get(type(x), type(x).__name__)


def data_notes(path: str, d) -> list:
    """Extra, content-level facts for the data files an agent asks about most."""
    name = Path(path).name
    out = []
    if name == "components.index.json" and isinstance(d, dict):
        items = d.get("items", [])
        by_r: dict = {}
        by_kind: dict = {}
        for it in items:
            by_r[it.get("r")] = by_r.get(it.get("r"), 0) + 1
            by_kind[it.get("kind")] = by_kind.get(it.get("kind"), 0) + 1
        out.append("by registry: " + ", ".join(f"{k} {v}" for k, v in sorted(by_r.items(), key=lambda kv: -kv[1])))
        out.append("by kind: " + ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])))
    elif name == "pool.json" and isinstance(d, dict):
        out.append("rows: " + ", ".join(f"{t['name']}({t.get('shape')},{t.get('license')})" for t in d.get("templates", [])))
    elif name == "registries.json" and isinstance(d, dict):
        out.append("indexed: " + ", ".join(f"{r['id']}({r.get('license')})" for r in d.get("registries", [])))
        out.append("refused: " + ", ".join(f"{r['id']}" for r in d.get("refused", [])))
    elif name == "bots.json" and isinstance(d, dict):
        out.append("bots: " + ", ".join(f"{b['id']}({b.get('kind')})" for b in d.get("bots", [])))
    elif name == "licenses.json" and isinstance(d, dict):
        out.append("accepted: " + ", ".join(d.get("accepted", {})) + " · refused: " + ", ".join(d.get("refused", {})))
    return out


# ---------------------------------------------------------------- anchors (curated core)

class Anchors:
    def __init__(self, files, mods, dh, tryon, api, errors):
        self.files, self.mods, self.errors = files, mods, errors
        self.dh = {c for c, _ in dh}
        self.tryon = {c for c, *_ in tryon}
        self.api = {c for c, *_ in api}
        self.broken: list = []
        self.used: set = set()

    def symbol_line(self, path: str, sym: str):
        info = self.mods.get(path)
        text = self.files.get(path) or ""
        if info and sym in info.get("symbols", {}):
            return info["symbols"][sym]
        if info and info.get("lang") == "md":
            for _lvl, h, ln in info["heads"]:
                if sym.lower() in h.lower():
                    return ln
        if Path(path).suffix in (".json", ".yml", ".yaml", ".sh", ".ps1", ".toml"):
            for i, ln in enumerate(text.split("\n"), 1):
                if re.search(r"""(^|["'\s])""" + re.escape(sym) + r"""(["':\s]|$)""", ln):
                    return i
        return None

    def resolve(self, ref: str, where: int) -> str:
        def bad(why):
            self.broken.append(f"{CORE}:{where}: [[{ref}]] — {why}")
            return f"⚠UNRESOLVED[{ref}]"
        if ref.startswith("dh:"):
            return f"`dh {ref[3:]}`" if ref[3:].split()[0] in self.dh else bad("no such dh subcommand")
        if ref.startswith("tryon:"):
            return f"`tryon {ref[6:]}`" if ref[6:].split()[0] in self.tryon else bad("no such tryon command")
        if ref.startswith("api:"):
            return f"`/__dh/api/{ref[4:]}`" if ref[4:] in self.api else bad("no such helper API route")
        if ref.startswith("!"):
            return ref[1:] if ref[1:] in self.errors else bad("error code raised nowhere")
        path, _, sym = ref.partition("#")
        fp = full(path, self.files)
        if not fp:
            return bad("no such file or directory")
        self.used.add(fp)
        if not sym:
            return short(fp)
        ln = self.symbol_line(fp, sym)
        return f"{sym}@{short(fp)}:{ln}" if ln else bad(f"symbol '{sym}' not found in {short(fp)}")

    def render(self, text: str) -> str:
        out = []
        for i, ln in enumerate(text.split("\n"), 1):
            out.append(re.sub(r"\[\[([^\]]+)\]\]", lambda m: self.resolve(m.group(1).strip(), i), ln))
        return "\n".join(out)


# ---------------------------------------------------------------- sections

def sec_map(files: dict, mods: dict) -> list:
    lines = ["`path  lines  purpose` — directories in order; a collapsed dir is one line.", ""]
    shown = set()
    cur_dir = None
    for path in sorted(files, key=lambda q: (Path(q).parent.as_posix(), Path(q).name)):
        text = files[path]
        c = collapsed(path)
        if c:
            if c[0] in shown:
                continue
            shown.add(c[0])
            n = sum(1 for p in files if p.startswith(c[0]))
            lines.append(f"{short(c[0])}  ({n} files)  {c[1]}")
            continue
        d = Path(path).parent.as_posix()
        if d != cur_dir:
            cur_dir = d
            label = ("./ (repo root)" if d == "." else f"{d}/ (skill root — the paths below are relative to it)"
                     if d + "/" == SKILL else short(d + "/"))
            lines.append(f"[{label}]")
        n = "bin" if text is None else str(text.count("\n") + (0 if text.endswith("\n") or not text else 1))
        lines.append(f"  {Path(path).name}  {n}  {purpose(path, text, mods.get(path))}".rstrip())
    return lines


def _loc(mods: dict, modpath: str, fn: str) -> str:
    info = mods.get(modpath) or mods.get(modpath + ".py") or {}
    ln = info.get("symbols", {}).get(fn)
    return f"{short(modpath)}:{ln}" if ln else short(modpath)


def sec_commands(files, mods, dh, handlers, tryon, api) -> list:
    L = ["### dh (python3 skills/deckhand/dh.py …) — parser: dhlib/cli.py build_parser; dispatch: dhlib/cli.py dispatch",
         "`command args → handlers@file:line`. Global: --project DIR (default: nearest dir with .deckhand/run.json, else package.json). "
         "Output: one JSON object; exit 0 ok · 1 check failed/refused ({ok:false,code,message,…}) · 2 usage.", ""]
    for c, spec in dh:
        h = handlers.get(c, {})
        calls = []
        for mod, fn in h.get("calls", []):
            if mod == "cli":
                calls.append(f"{fn}@dhlib/cli.py:{mods[SKILL + 'dhlib/cli.py']['symbols'].get(fn)}")
            else:
                mp = SKILL + f"dhlib/{mod}.py"
                calls.append(f"{mod}.{fn}@{_loc(mods, mp, fn).split(':')[-1] if ':' in _loc(mods, mp, fn) else '?'}")
        args = [a for a in spec["args"] if not a.startswith("[--project")]
        plain = [a.split("  # ")[0] for a in args]
        helps = [a for a in args if "  # " in a]
        head = f"dh {c} {' '.join(plain)}".rstrip()
        L.append(f"- {head}" + (f"  — {spec['help']}" if spec["help"] else ""))
        if calls:
            L.append(f"    → dispatch L{h['line']}: " + ", ".join(calls))
        for hl in helps:
            a, _, t = hl.partition("  # ")
            L.append(f"    {a.strip('[]').split()[0]}: {t}")
    L += ["", "### tryon (node skills/deckhand/tryon/cli.mjs …, or `dh tryon …`) — switch in tryon/cli.mjs main",
          "flags: --project DIR (default .). Output: one JSON line; exit 0 ok, 1 failed, 2 usage.", ""]
    for c, line, usage, calls in tryon:
        where = ", ".join(f"{short(m).split('/')[-1].split('.')[0]}.{f}@{_loc(mods, m, f).split(':')[-1]}" for m, f in calls)
        L.append(f"- tryon {c} {usage}".rstrip() + f"  [cli.mjs:{line}]" + (f" → {where}" if where else ""))
    L += ["", "### helper HTTP API (tryon serve) — POST /__dh/api/<name>, header x-dh-token; switch in tryon/server.mjs api()",
          "Other routes: GET /__dh/overlay.js (the UI) · GET /__dh/events?t=TOKEN (SSE progress) · everything else = reverse proxy to the dev server with the overlay <script> injected into HTML.", ""]
    for c, line, calls in api:
        where = ", ".join(f"{short(m).split('/')[-1].split('.')[0]}.{f}@{_loc(mods, m, f).split(':')[-1]}" for m, f in calls)
        L.append(f"- {c}  [server.mjs:{line}]" + (f" → {where}" if where else ""))
    return L


def sec_modules(files, mods, used_by, curated) -> list:
    L = ["Per code file: purpose (its own header, verbatim) · deps (internal imports) · used-by · api (public: name(params)@line — doc) · "
         "int (internal name@line) · const. Order: control plane, try-on, ops, templates, repo scripts.", ""]
    code = [p for p in mods if mods[p].get("lang") in ("py", "js") and not is_test(p)]
    rank = lambda p: (0 if "/dhlib/" in p or p.endswith("dh.py") else 1 if "/tryon/" in p else 2 if "/ops/" in p else 3 if "/templates/" in p else 4, p)  # noqa: E731
    uncurated = [short(p) for p in sorted(code, key=rank) if p not in curated and "/templates/" not in p and files[p].strip()]
    if uncurated:
        L.append("Not referenced by the curated core (only this generated entry describes them): " + ", ".join(uncurated))
        L.append("")
    for p in sorted(code, key=rank):
        info = mods[p]
        n = files[p].count("\n")
        L.append(f"#### {short(p)}  ({n} lines, {info['lang']})")
        if info.get("error"):
            L.append(f"  PARSE ERROR: {info['error']}")
        doc = info.get("doc", "").strip()
        if doc:
            for dl in doc.split("\n"):
                if dl.strip():
                    L.append("  | " + dl.rstrip())
        if info.get("deps"):
            L.append("  deps: " + ", ".join(short(d) for d in info["deps"]))
        if used_by.get(p):
            L.append("  used-by: " + ", ".join(short(d) for d in sorted(used_by[p])))
        for r in info.get("api", []):
            sig = r.get("sig", "")
            call = r["name"] if sig == "class" else f"{r['name']}({sig})" if "sig" in r else r["name"]
            L.append(f"  api {('class ' if sig == 'class' else '')}{call}@{r['line']}" + (f" — {one(r['doc'], 120)}" if r.get("doc") else ""))
        if info.get("internal"):
            L.append("  int: " + " ".join(f"{r['name']}@{r['line']}" for r in info["internal"]))
        if info.get("consts"):
            L.append("  const: " + " ".join(f"{r['name']}@{r['line']}" for r in info["consts"]))
    return L


def sec_errors(errors: dict) -> list:
    L = ["`CODE  where (file:line) — message start`. dh prints {ok:false, code, message}; tryon prints {ok:false, code, message}; "
         "the helper API returns the same with HTTP 4xx.", ""]
    for code in sorted(errors):
        locs = errors[code]
        where = ", ".join(sorted({f"{p}:{ln}" for p, ln, _ in locs}, key=lambda s: (s.split(":")[0], int(s.split(":")[1]))))
        msg = next((m for _, _, m in locs if m), "")
        L.append(f"- {code}  {where}" + (f" — {msg}" if msg else ""))
    return L


def sec_env(env: dict) -> list:
    L = ["Environment variables read by the code (tests set more; see §TESTS files).", ""]
    for k in sorted(env):
        L.append(f"- {k}  " + ", ".join(sorted({f'{p}:{ln}' for p, ln, _ in env[k]})))
    return L


def sec_data(files: dict) -> list:
    L = ["Shape legend: {key:type} · [N×item] · s string · n number · b bool. Query data through commands (dh pool query, tryon query) instead of reading it.", ""]
    for path, text in files.items():
        if text is None or collapsed(path):
            continue
        if not (path.startswith(SKILL + "data/") or path.startswith(SKILL + "templates/")) or Path(path).suffix not in (".json", ".jsonl"):
            continue
        try:
            if path.endswith(".jsonl"):
                rows = [json.loads(x) for x in text.split("\n") if x.strip()]
                L.append(f"- {short(path)}  jsonl {len(rows)} rows × {shape(rows[0]) if rows else '{}'}")
                if Path(path).name == "lessons.seed.jsonl":
                    for r in rows:
                        L.append(f"    {r.get('id')} [{r.get('phase')}/{r.get('rung')}] {one(r.get('symptom'), 70)} → {one(r.get('fix'), 90)}")
                continue
            d = json.loads(text)
        except ValueError:
            L.append(f"- {short(path)}  (unparsable json)")
            continue
        L.append(f"- {short(path)}  {shape(d)}")
        for note in data_notes(path, d):
            L.append(f"    {one(note, 400)}")
    n = sum(1 for p in files if p.startswith(SKILL + "data/pool/"))
    if n:
        sample = next(p for p in files if p.startswith(SKILL + "data/pool/"))
        try:
            L.append(f"- data/pool/*.json  {n} files, each {shape(json.loads(files[sample]))}")
        except ValueError:
            pass
    return L


def sec_docs(files: dict, mods: dict) -> list:
    L = ["Every markdown file: `path (lines): # title › ## sections`. Load a reference only when `dh next` names it.", ""]
    for p in files:
        info = mods.get(p)
        if not info or info.get("lang") != "md" or p == CORE:
            continue
        heads = info["heads"]
        n = files[p].count("\n")
        if Path(p).name == "CHANGELOG.md":
            items = [h for lvl, h, _ in heads if lvl == 2][:6]
        else:
            items = [("## " if lvl == 2 else "### " if lvl == 3 else "# ") + h for lvl, h, _ in heads][:40]
        L.append(f"- {short(p)} ({n}): " + " › ".join(one(x, 70) for x in items))
    return L


def sec_tests(files: dict, mods: dict) -> list:
    L = ["Run: `python3 -m unittest discover -s skills/deckhand/tests` · `python3 -m pytest skills/deckhand/ops/tests -q` · "
         "`node --test skills/deckhand/tryon/test/*.test.mjs` · `python3 -m unittest discover -s scripts -p 'test_*.py'`. "
         "All offline (registry HTTP = recorded fixtures; GitHub = a local mock API + file:// remotes).", ""]
    total = 0
    for p, text in files.items():
        if text is None or collapsed(p) or not is_test(p) or Path(p).suffix not in (".py", ".mjs"):
            continue
        names = []
        if p.endswith(".py"):
            try:
                t = ast.parse(text)
            except SyntaxError:
                continue
            for n in ast.walk(t):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                    names.append((n.name, n.lineno))
            targets = sorted({m.group(1) for m in re.finditer(r"(?:from|import)\s+(?:dhlib\.|scripts\.)?(\w+)", text)
                              if (SKILL + f"dhlib/{m.group(1)}.py") in files or (SKILL + f"ops/scripts/{m.group(1)}.py") in files or f"scripts/{m.group(1)}.py" in files})
        else:
            for i, ln in enumerate(text.split("\n"), 1):
                m = re.match(r"""^\s*(?:test|it)\(\s*(['"`])(.+?)\1""", ln)
                if m:
                    names.append((m.group(2), i))
            targets = sorted({Path(m.group(1)).name for m in re.finditer(r"from\s+'(\.\./[^']+)'", text)})
        if not names:
            if "helper" in p or "fixtures" in p:
                L.append(f"- {short(p)}: helpers")
            continue
        total += len(names)
        L.append(f"- {short(p)} ({len(names)}) covers {', '.join(targets) or '—'}")
        for nm, ln in names:
            L.append(f"    {ln}: {one(nm, 140)}")
    L.insert(2, f"{total} test cases.")
    return L


def sec_ci(files: dict) -> list:
    L = []
    for p, text in files.items():
        if not p.startswith(".github/workflows/") or text is None:
            continue
        on = re.search(r"^on:[ \t]*\n((?:[ \t]+.*\n)+)", text, re.M)
        L.append(f"- {p}: {purpose(p, text, None)}" + (f" · on: {one(on.group(1), 80)}" if on else ""))
        for m in re.finditer(r"^\s*-\s*name:\s*(.+)\n\s*run:\s*(.+)$", text, re.M):
            L.append(f"    {one(m.group(1), 60)}: `{one(m.group(2), 150)}`")
    for p, text in files.items():
        if p.startswith(".githooks/") and text is not None:
            L.append(f"- {p}: {purpose(p, text, None)}")
    return L


# ---------------------------------------------------------------- assemble

def build(files: dict) -> tuple:
    mods = analyze(files)
    dh, handlers = dh_commands(files, mods)
    tryon = tryon_commands(files)
    api = api_routes(files)
    errors = scan_index(files, ERR_PATTERNS)
    env = scan_index(files, ENV_PATTERNS)
    used_by: dict = {}
    for p, info in mods.items():
        for d in info.get("deps", []):
            used_by.setdefault(d, set()).add(p)

    anchors = Anchors(files, mods, dh, tryon, api, errors)
    core_text = files.get(CORE) or ""
    core = anchors.render(core_text)
    curated_sections = []
    for block in re.split(r"(?m)^## ", core)[1:]:
        title, _, body = block.partition("\n")
        curated_sections.append((title.strip(), body.strip("\n").split("\n")))
    preamble = re.split(r"(?m)^## ", core)[0].strip()

    gen_sections = [
        ("MAP [gen] — every file", sec_map(files, mods)),
        ("COMMANDS [gen] — dh, tryon, helper API → handlers", sec_commands(files, mods, dh, handlers, tryon, api)),
        ("MODULES [gen] — every code file", sec_modules(files, mods, used_by, anchors.used)),
        ("ERRORS [gen] — code → where raised", sec_errors(errors)),
        ("ENV [gen] — variables read", sec_env(env)),
        ("DATA [gen] — shipped data + templates", sec_data(files)),
        ("DOCS [gen] — markdown outline", sec_docs(files, mods)),
        ("TESTS [gen] — what proves what", sec_tests(files, mods)),
        ("CI + HOOKS [gen]", sec_ci(files)),
    ]
    sections = [(t + ("" if "[" in t else " [cur]"), b) for t, b in curated_sections] + gen_sections

    skill_md = files.get(SKILL + "SKILL.md") or ""
    version = (re.search(r"^version:\s*(\S+)", skill_md, re.M) or [None, "?"])[1]
    h = hashlib.sha256()
    for p, t in files.items():
        h.update(p.encode() + b"\0" + (t.encode() if t is not None else b"<bin>") + b"\0")
    fp = h.hexdigest()[:12]
    n_code = sum(1 for p in mods if mods[p].get("lang") in ("py", "js"))

    head = [
        f"# LLM_CONTEXT — Deckhand v{version}",
        f"<!-- GENERATED by scripts/llm_context.py from {len(files)} files ({n_code} code) · fingerprint {fp}. "
        f"Do not edit: change the code or {CORE}, then `python3 scripts/llm_context.py`. -->",
        "",
    ]
    n_cur = len(curated_sections)
    cur_tokens = sum(len("\n".join(b)) for _, b in curated_sections) // 4
    head += [f"READ: curated §0–§{n_cur - 1} (~{cur_tokens // 1000 + 1}k tokens) fully, in order. "
             f"§{n_cur}–§{len(sections) - 1} are generated lookup tables: jump by the INDEX line ranges or grep; don't read them through.", ""]
    if preamble:
        head += preamble.split("\n") + [""]
    # index with exact line ranges (the index has a fixed height, so ranges can be computed up front)
    idx_len = len(sections) + 2
    start = len(head) + idx_len + 1
    ranges = []
    for i, (title, body) in enumerate(sections):
        blen = 2 + len(body) + 1                    # heading, blank, body, blank
        ranges.append((i, title, start, start + blen - 2))
        start += blen
    idx = ["## INDEX (section: lines in this file)", *[f"- §{i} {t}: L{a}-L{b}" for i, t, a, b in ranges], ""]
    assert len(idx) == idx_len, "index height changed"
    out = head + idx
    for i, (title, body) in enumerate(sections):
        out += [f"## §{i} {title}", "", *body, ""]
    text = "\n".join(out).rstrip("\n") + "\n"
    return text, anchors.broken


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build LLM_CONTEXT.md (see the module docstring).")
    ap.add_argument("--check", action="store_true", help="exit 1 if the file is stale or an anchor is broken; write nothing")
    ap.add_argument("--index", action="store_true", help="read the git index instead of the working tree (pre-commit)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    files = load_tree(index=a.index)
    for p in files:
        s = short(p)
        if not p.startswith(SKILL) and full(s, {q: None for q in files if q.startswith(SKILL)}):
            print(f"llm_context: {p} collides with a skill path — rename it or change the path rule", file=sys.stderr)
            return 2
    text, broken = build(files)
    for b in broken:
        print("llm_context: broken anchor " + b, file=sys.stderr)
    target = ROOT / OUT
    current = target.read_text(encoding="utf-8").replace("\r\n", "\n") if target.exists() else ""
    if a.check:
        if current != text:
            old, new = current.split("\n"), text.split("\n")
            diff = [f"  L{i + 1}: {one(n, 100)}" for i, (o, n) in enumerate(zip(old, new)) if o != n][:8]
            print(f"llm_context: {OUT} is STALE — run `python3 scripts/llm_context.py` and commit it.", file=sys.stderr)
            for d in diff:
                print(d, file=sys.stderr)
            return 1
        if not a.quiet:
            print(f"llm_context: {OUT} is fresh ({len(text.splitlines())} lines)")
        return 1 if broken else 0
    if current != text:
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if not a.quiet:
        print(f"llm_context: {OUT} {'updated' if current != text else 'unchanged'} ({len(text.splitlines())} lines, ~{len(text) // 4} tokens)")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
