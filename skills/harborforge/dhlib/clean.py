"""dh clean: remove what Deckhand and its known tools leave behind (temp folders, browser profiles, stranded
sibling folders). Dry run by default. Patterns are data (data/clean.json). Never follows a link out of a folder,
and only touches direct children of the temp dir (or of the project's parent, for siblings)."""
from __future__ import annotations

import os
import re
import stat
import tempfile
import time
from pathlib import Path

from .util import DATA, DhError, read_json, run, which

CFG = read_json(DATA / "clean.json", {}) or {}
MB = 1024 * 1024


def _is_link(p) -> bool:
    """A symlink, or a Windows junction/reparse point: something that points elsewhere."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _size(p) -> int:
    total = 0
    stack = [str(p)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if _is_link(e.path):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def _age_hours(p, now: float) -> float:
    """Age of the newest thing at the top of the folder (a folder in use has fresh children)."""
    newest = 0.0
    try:
        newest = os.lstat(p).st_mtime
        with os.scandir(p) as it:
            for e in it:
                try:
                    newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return max(0.0, (now - newest) / 3600)


def _rm_link(p: str) -> None:
    try:
        os.unlink(p)
    except OSError:
        os.rmdir(p)                                          # a junction: removes the link, never its target


def _rm_file(p: str, retries: int) -> None:
    for i in range(retries):
        try:
            os.chmod(p, stat.S_IWRITE)
            os.unlink(p)
            return
        except FileNotFoundError:
            return
        except OSError:
            if i == retries - 1:
                raise
            time.sleep(0.2)


def remove_tree(path, retries: int = 3) -> None:
    """Delete a folder without ever descending into a link; read-only files (git objects on Windows) get chmod +w."""
    path = str(path)
    if _is_link(path):
        _rm_link(path)
        return
    with os.scandir(path) as it:
        entries = list(it)
    for e in entries:
        if _is_link(e.path):
            _rm_link(e.path)
        elif e.is_dir(follow_symlinks=False):
            remove_tree(e.path, retries)
        else:
            _rm_file(e.path, retries)
    for i in range(retries):
        try:
            os.chmod(path, stat.S_IRWXU)
            os.rmdir(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if i == retries - 1:
                raise
            time.sleep(0.2)


def _temp_kind(name: str, p: Path) -> str | None:
    if any(name.startswith(x) for x in CFG.get("temp_prefixes", [])):
        return "scaffold" if name.startswith("dh-scaffold-") else "temp"
    if any(name.startswith(x) for x in CFG.get("browser_profile_prefixes", [])):
        return "browser-profile"
    py = CFG.get("python_tmp") or {}
    if re.match(py.get("regex", "^$"), name) and not _is_link(p) and p.is_dir() and any((p / m).exists() for m in py.get("markers", [])):
        return "python-tmp"
    return None


def _sibling_kind(name: str) -> str | None:
    sib = CFG.get("sibling") or {}
    if name.startswith(sib.get("scaffold_prefix", "dh-scaffold-")):
        return "scaffold"
    if name.startswith(".") and name.endswith(sib.get("hold_suffix", ".deckhand-hold")):
        return "hold"
    return None


def _candidates(temp: Path, project: Path | None):
    scans = [(temp, False)]
    if project is not None and os.path.realpath(project.parent) != os.path.realpath(temp):
        scans.append((project.parent, True))
    for base, sibling in scans:
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            p = base / name
            kind = _sibling_kind(name) if sibling else _temp_kind(name, p)
            if kind and (_is_link(p) or p.is_dir()):
                yield p, kind, sibling


def _hold_stranded(hold: Path, project: Path | None) -> bool:
    """A hold that still carries Deckhand files the project lacks must not be deleted."""
    try:
        if not any(hold.iterdir()):
            return False
    except OSError:
        return True
    return not (project is not None and (project / ".deckhand").exists())


def clean(temp_root=None, project=None, apply: bool = False, older_than: float | None = None, caches: bool = False, now: float | None = None) -> dict:
    temp = Path(temp_root) if temp_root else Path(tempfile.gettempdir())
    if not temp.is_dir():
        raise DhError("NO_TEMP", f"{temp} is not a folder")
    hours = float(CFG.get("min_age_hours", 2) if older_than is None else older_than)
    now = time.time() if now is None else now
    proj = Path(project).resolve() if project else None
    found, skipped, young = [], [], 0
    for p, kind, sibling in _candidates(temp, proj):
        base = proj.parent if sibling else temp
        if os.path.realpath(p.parent) != os.path.realpath(base):
            skipped.append({"path": str(p), "why": "outside the scanned folder"})
            continue
        if kind == "hold" and p.name != f".{proj.name}.deckhand-hold":
            skipped.append({"path": str(p), "why": "hold of another project"})
            continue
        if kind == "hold" and _hold_stranded(p, proj):
            skipped.append({"path": str(p), "why": "holds Deckhand files the project lacks: move them back first"})
            continue
        age = _age_hours(p, now)
        if age < hours:
            young += 1
            continue
        link = _is_link(p)
        nbytes = 0 if link else _size(p)
        found.append({"path": str(p), "kind": kind, "mb": round(nbytes / MB, 1), "age_hours": round(age, 1),
                      **({"link": True} if link else {}), "_bytes": nbytes})
    total = sum(f["_bytes"] for f in found)
    out = {"found": [{k: v for k, v in f.items() if k != "_bytes"} for f in found], "total_mb": round(total / MB, 1),
           "older_than_hours": hours, "skipped_young": young, "applied": bool(apply)}
    if skipped:
        out["skipped"] = skipped
    if apply:
        removed, failed, freed = [], [], 0
        for f in found:
            try:
                remove_tree(f["path"])
                removed.append(f["path"])
                freed += f["_bytes"]
            except OSError as e:
                failed.append({"path": f["path"], "why": f"{type(e).__name__}: {e}"})
        out.update(removed=removed, failed=failed, freed_mb=round(freed / MB, 1))
    else:
        out["next"] = "dh clean --apply" if found else "nothing to clean"
    if caches:
        out["caches"] = _caches(apply)
    return out


def _caches(apply: bool) -> dict:
    """Official cleaners only: `npm cache verify`. The pnpm store is reported, never touched."""
    res: dict = {}
    if which("npm"):
        r = run(["npm", "config", "get", "cache"], timeout=60)
        d = Path((r["out"] or "").strip() or ".") / "_cacache"
        res["npm"] = {"dir": str(d), "mb": round(_size(d) / MB, 1) if d.is_dir() else 0.0}
        if apply:
            v = run(["npm", "cache", "verify"], timeout=900)
            res["npm"]["verified"] = v["code"] == 0
            res["npm"]["mb_after"] = round(_size(d) / MB, 1) if d.is_dir() else 0.0
    if which("pnpm"):
        r = run(["pnpm", "store", "path"], timeout=60)
        d = Path((r["out"] or "").strip() or ".")
        res["pnpm"] = {"dir": str(d), "mb": round(_size(d) / MB, 1) if d.is_dir() else 0.0, "note": "report only: `pnpm store prune` is the owner's call"}
    return res
