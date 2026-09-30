"""One scrubber for every free-text sink (notes, lessons, research, pending, blackboard, brief, RESUME, HANDOFF, runs).

  scrub_text(s)   secrets out: every vault value (project + machine layers, legacy keyring) matched literally, the shared
                  credential shapes (data/secrets.json), 'password=..' / 'token: ..' assignments, URL credentials, long
                  key-like runs (32+ chars, mixed classes; the `<id>|<token>` Coolify shape), private key blocks
  scrub_obj(x)    the same over every string of a JSON-like structure
  norm_paths(s)   a personal path becomes a placeholder: <home>, <tmp>, <project> (both slash styles, any drive letter)
  clean_text(s)   both: what may be stored or shown

Wiring still to do by the owners of those files: plan.bb_post (msg), state/cli `brief set` (values), pending.add (text, why, how, where)
and their stdout echoes call `scrub_text` before writing/returning.
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import redact as _redact

PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S)
COOLIFY_TOKEN = re.compile(r"(?<![\w|])\d{1,6}\|[A-Za-z0-9]{30,}(?!\w)")
SK_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*")
AKIA = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
LONG_RUN = re.compile(r"(?<![\w/.\\-])[A-Za-z0-9+/_=-]{32,}(?![\w/.\\-])")
_PW = re.compile(r"""(?i)\b((?:pass(?:word|wd|phrase)?|pwd)["']?\s*[=:]\s*["']?)([^\s"'`,;&]{4,})""")
_TK = re.compile(r"""(?i)\b((?:[a-z_]*(?:token|secret|api[_ -]?key|apikey|private[_ -]?key))["']?\s*[=:]\s*["']?(?:bearer\s+)?)([^\s"'`,;&]{6,})""")
_FILLER = {"none", "n/a", "see", "stored", "required", "needed", "reset", "changed", "yours", "unknown", "empty", "hidden", "redacted",
           "manager", "vault", "below", "above", "here", "there", "again", "rotate", "rotated"}


def secret_values() -> list:
    """Every stored secret the owner has: project + machine vault layers and the legacy ops keyring."""
    try:
        from . import profile as PROFILE
        vals = list(PROFILE.vault_read().values()) + list(PROFILE.legacy_read().values())
        return [v for v in vals if isinstance(v, str)]
    except Exception:
        return []


def _looks_secret(v: str, strict: bool) -> bool:
    if v.startswith(("~", "/", "$", "<", "{", "[", "(", "*", ".", "#", "%")) or "***" in v or v.lower() in _FILLER:
        return False
    if strict:
        return True
    return len(v) >= 8 and not v.startswith("http") and (bool(re.search(r"\d", v)) or (bool(re.search(r"[a-z]", v)) and bool(re.search(r"[A-Z]", v))))


def _long_run(m) -> str:
    w = m.group(0)
    if not (re.search(r"\d", w) and re.search(r"[A-Za-z]", w)):
        return w
    if re.fullmatch(r"[0-9a-fA-F]+", w):
        return w if (len(w) in (40, 64) and w == w.lower()) else "***"      # a git / sha256 id is a name, not a key
    mixed = bool(re.search(r"[a-z]", w)) and bool(re.search(r"[A-Z]", w))
    return "***" if (mixed or re.search(r"[+/=]", w) or (len(w) >= 40 and "-" not in w)) else w


def scrub_text(text, extra_values=()) -> str:
    """Secrets out of free text. Idempotent, never raises."""
    if not text:
        return text if isinstance(text, str) else ""
    text = str(text)
    vals = [v for v in list(secret_values()) + list(extra_values) if v and len(v) >= 6]
    for v in sorted(set(vals), key=len, reverse=True):
        text = text.replace(v, "***")
    text = PRIVATE_KEY_BLOCK.sub("***PRIVATE KEY REMOVED***", text)
    text = _redact(text, vals)
    for rx in (COOLIFY_TOKEN, SK_KEY, JWT, AKIA):
        text = rx.sub("***", text)
    text = _PW.sub(lambda m: m.group(1) + ("***" if _looks_secret(m.group(2), True) else m.group(2)), text)
    text = _TK.sub(lambda m: m.group(1) + ("***" if _looks_secret(m.group(2), False) else m.group(2)), text)
    return LONG_RUN.sub(_long_run, text)


def scrub_obj(obj, extra_values=()):
    if isinstance(obj, str):
        return scrub_text(obj, extra_values)
    if isinstance(obj, list):
        return [scrub_obj(x, extra_values) for x in obj]
    if isinstance(obj, tuple):
        return tuple(scrub_obj(x, extra_values) for x in obj)
    if isinstance(obj, dict):
        return {k: scrub_obj(v, extra_values) for k, v in obj.items()}
    return obj


# ------------------------------------------------------------------ personal paths

_SEP = r"[\\/]+"
_NAME = r"[^\\/\s'\"`:;,)\]}]+"
_TAIL = r"(?:[\\/][^\s'\"`;,)\]}]*)?"


def _variants(p) -> list:
    s = str(p)
    return sorted({s, s.replace("\\", "/"), s.replace("/", "\\")}, key=len, reverse=True)


def norm_paths(text, root=None) -> str:
    """<project> for the project folder, <tmp> for temp locations, <home> for any user's home (Windows on any drive, both
    slash styles, /c/Users, /home, /Users): the same failure on another machine then has the same text."""
    if not text:
        return text if isinstance(text, str) else ""
    text = str(text)
    roots = [root] if root else []
    if root:
        try:
            roots.append(Path(root).resolve())
        except OSError:
            pass
    for r in roots:
        for v in _variants(r):
            if len(v) > 3:
                text = re.sub(re.escape(v), "<project>", text, flags=re.I if re.match(r"[A-Za-z]:", v) else 0)
    text = re.sub(r"(?i)(?<![\w.<])(?:[a-z]:|/[a-z])" + _SEP + r"Users" + _SEP + _NAME + _SEP + r"AppData" + _SEP + r"Local" + _SEP + r"Temp" + _TAIL, "<tmp>", text)
    text = re.sub(r"(?i)(?<![\w.<])(?:[a-z]:|/[a-z])" + _SEP + r"Users" + _SEP + _NAME, "<home>", text)
    text = re.sub(r"(?<![\w.<])/(?:home|Users)/" + _NAME, "<home>", text)
    text = re.sub(r"(?<![\w.<])/(?:tmp|var/tmp)/[^\s'\"`;,)\]}]+", "<tmp>", text)
    try:
        for v in _variants(Path.home()):
            if len(v) > 3:
                text = re.sub(re.escape(v), "<home>", text, flags=re.I if re.match(r"[A-Za-z]:", v) else 0)
    except Exception:
        pass
    return text


def clean_text(text, root=None) -> str:
    return norm_paths(scrub_text(text), root)


def clean_obj(obj, root=None):
    if isinstance(obj, str):
        return clean_text(obj, root)
    if isinstance(obj, list):
        return [clean_obj(x, root) for x in obj]
    if isinstance(obj, dict):
        return {k: clean_obj(v, root) for k, v in obj.items()}
    return obj


def signature_paths(sig: str) -> str:
    """A regex signature that names one person's folder must match on any machine: the user part becomes \\S+?"""
    sig = re.sub(r"(?i)[a-z]:(?:\\\\|[\\/])+Users(?:\\\\|[\\/])+[^\\/\s]+", r"\\S+?", sig)
    return re.sub(r"(?<![\w.])/(?:home|Users)/[^\\/\s]+", r"\\S+?", sig)
