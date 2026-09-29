#!/usr/bin/env python3
"""repo_presence.py — render an app's public face from ONE filled JSON.

Takes a filled copy of ``templates/ops/repo-presence/repo.example.json`` and writes:

- ``README.md``   from ``README.template.md`` — sections with no content are dropped,
                  placeholders that never got data fail loudly (no half-READMEs).
- ``LICENSE``     proprietary notice; when ``license_derived_from`` is set, the
                  upstream MIT notice is retained at the bottom (compliance).
- ``package.json`` metadata only — ``name`` / ``version`` / ``description`` /
                  ``license`` get set; everything else is left untouched.

It also prints the exact GitHub commands (description, topics, set-default) and
with ``--gh`` runs them (and, when repo.json carries enough info, tells you the
release command to finish the pass).

Usage:
  py ops/scripts/repo_presence.py init repo.json [--dir <project>] [--dry-run] [--gh]
  python3 ops/scripts/repo_presence.py init repo.json

Exit codes: 0 ok · 2 bad input (missing field, leftover placeholder, bad license mode).

Style rules this enforces (no fluff): facts only, present tense, one line per
feature — never a list of internal details, never a promise the product doesn't keep.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "ops" / "repo-presence"

REQUIRED = ["repo", "name", "tagline", "live_url", "version", "intro", "stack", "deploy_notes"]

MIT_TEXT = """MIT License

Copyright (c) 2025 Vercel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""


def fail(msg):
    print(f"repo_presence: {msg}", file=sys.stderr)
    sys.exit(2)


def load_data(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read {path}: {e}")
    missing = [k for k in REQUIRED if not str(data.get(k, "")).strip()]
    if missing:
        fail("repo.json is missing required fields: " + ", ".join(missing))
    if data.get("license") not in (None, "proprietary", "mit", "apache-2.0"):
        fail(f"license must be one of proprietary|mit|apache-2.0, got {data.get('license')!r}")
    return data


def _stringify(val):
    if isinstance(val, list):
        return "\n".join(str(v) for v in val)
    return "" if val is None else str(val)


def render_readme(data):
    tpl = (TEMPLATES / "README.template.md").read_text(encoding="utf-8")
    out = re.sub(
        r"<!--if:([A-Z_]+)-->(.*?)<!--/if:\1-->",
        lambda m: m.group(2) if str(data.get(m.group(1).lower(), "")).strip() else "",
        tpl,
        flags=re.S,
    )

    def tok(m):
        key = m.group(1).lower()
        if key in data:
            val = _stringify(data[key])
            if val.strip():
                return val
        if key == "env_note":  # allowed to vanish silently
            return ""
        fail(f"template token {{{{{m.group(1)}}}}} has no value in repo.json")

    out = re.sub(r"\{\{([A-Z_]+)\}\}", tok, out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"
    if "{{" in out:
        fail("placeholders left after render — fix the template/data")
    return out


def render_license(data):
    if data.get("license") != "proprietary":
        return None
    tpl = (TEMPLATES / "LICENSE.proprietary.txt").read_text(encoding="utf-8")
    text = (
        tpl.replace("{{NAME}}", str(data["name"]))
        .replace("{{OWNER}}", str(data.get("license_owner", "")))
        .replace("{{YEAR}}", str(datetime.date.today().year))
        .rstrip()
        + "\n"
    )
    if data.get("license_derived_from"):
        text += (
            f"\nPortions of this codebase derive from {data['license_derived_from']}. "
            "The original license and copyright notice are retained below and apply to those portions.\n"
            "\n" + ("-" * 74) + "\n\n" + MIT_TEXT + "\n"
        )
    return text


def patch_package_json(path, data):
    if not data.get("package_json"):
        return None
    p = Path(path)
    if not p.is_file():
        fail(f"package.json not found at {p} — set package_json to false or point --dir at the project")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"package.json is not valid JSON: {e}")
    updates = {
        "name": data.get("package_name") or re.sub(r"[^a-z0-9-]+", "-", str(data["name"]).lower()).strip("-"),
        "version": data.get("version"),
        "description": data.get("description"),
        "license": "UNLICENSED" if data.get("license") in (None, "proprietary") else str(data["license"]).upper(),
    }
    changed = {}
    for k, v in updates.items():
        if v and obj.get(k) != v:
            obj[k] = v
            changed[k] = v
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n", changed


def gh_commands(data):
    repo = data["repo"]
    cmds = [f"gh repo set-default {repo}"]
    if data.get("description"):
        cmds.append(f'gh repo edit {repo} --description "{data["description"]}"')
    if data.get("topics"):
        topics = " ".join(f"-f 'names[]={t}'" for t in data["topics"])
        cmds.append(f"gh api --method PUT repos/{repo}/topics {topics}")
    cmds.append(f'git tag v{data["version"]} && git push origin v{data["version"]}    # then: gh release create v{data["version"]} -R {repo} --latest --notes "<user-facing notes>"')
    return cmds


def run_gh(data):
    results = []
    steps = [["gh", "repo", "set-default", data["repo"]]]
    if data.get("description"):
        steps.append(["gh", "repo", "edit", data["repo"], "--description", data["description"]])
    if data.get("topics"):
        args = ["gh", "api", "--method", "PUT", f"repos/{data['repo']}/topics"]
        for t in data["topics"]:
            args += ["-f", f"names[]={t}"]
        steps.append(args)
    for step in steps:
        try:
            r = subprocess.run(step, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
            results.append((step[:4], r.returncode, (r.stdout or r.stderr).strip()[:200]))
        except FileNotFoundError:
            results.append((step[:4], 127, "gh CLI not found — run the printed commands manually"))
            break
    return results


def cmd_init(a):
    data = load_data(a.data)
    d = Path(a.dir)
    outputs = [(d / "README.md", render_readme(data))]
    lic = render_license(data)
    if lic:
        outputs.append((d / "LICENSE", lic))
    pkg = patch_package_json(d / "package.json", data)
    if pkg:
        outputs.append((d / "package.json", pkg[0]))

    for path, content in outputs:
        if a.dry_run:
            print(f"would write {path} ({len(content.splitlines())} lines)")
        else:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path}")
    if pkg and pkg[1]:
        print("package.json updated: " + ", ".join(f"{k}={v!r}" for k, v in pkg[1].items()))

    print("\nGitHub steps:")
    for c in gh_commands(data):
        print("  " + c)
    if a.gh:
        print("\nRunning GitHub steps (--gh):")
        for step, rc, out in run_gh(data):
            print(f"  {' '.join(step)} -> rc={rc} {out}")
    if not a.dry_run:
        print("\nNext: git add README.md LICENSE package.json && git commit — the release (tag + notes) finishes the pass.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="repo_presence.py", description="Render an app repo's public face from one filled JSON.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="render README/LICENSE/package.json metadata from a filled repo.json")
    p.add_argument("data", help="path to your filled copy of templates/ops/repo-presence/repo.example.json")
    p.add_argument("--dir", default=".", help="project directory to write into (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="show what would be written, write nothing")
    p.add_argument("--gh", action="store_true", help="also run the gh commands (set-default/description/topics)")
    a = ap.parse_args(argv)
    return cmd_init(a)


if __name__ == "__main__":
    sys.exit(main())
