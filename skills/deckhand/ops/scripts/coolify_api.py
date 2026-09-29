#!/usr/bin/env python3
"""Thin Coolify REST client (stdlib only) — used by `dh deploy` and the ops runbooks.

Config precedence: --url/--token flags > COOLIFY_URL/COOLIFY_TOKEN env > this project's own layer (`dh profile where`)
> the deckhand vault (~/.deckhand/vault.env: COOLIFY_TOKEN; ~/.deckhand/profile.json: coolify.url) > v1's ~/.vps-ops/config.json
> v1's token fallback in ~/.vps-ops/secrets/env.sh.
See references/ops/10-bootstrap-vps.md for setup, references/ops/40-change-pipeline.md for usage.
"""
import argparse
import html
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("VPS_OPS_HOME", str(Path.home() / ".vps-ops")))

# Tolerated deployment status sets (live-confirmed 2026-09-17 on Coolify 4.3.21: terminal OK = "finished").
OK_STATUS = {"success", "finished"}
FAIL_STATUS = {"failed", "cancelled"}


def deckhand_config(dk):
    """(vault dict, coolify.url) from a deckhand home — the same single-quoted KEY='value' format dh writes."""
    import shlex
    vault = {}
    vf = Path(dk) / "vault.env"
    if vf.exists():
        for line in vf.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                try:
                    parts = shlex.split(v.strip())
                    vault[k.replace("export ", "").strip()] = parts[0] if len(parts) == 1 else v.strip()
                except ValueError:
                    vault[k.strip()] = v.strip().strip("'\"")
    try:
        prof = (json.loads((Path(dk) / "profile.json").read_text(encoding="utf-8")).get("coolify") or {}).get("url")
    except (OSError, ValueError):
        prof = None
    return vault, prof


def project_layer():
    """This project's own layer (`dh profile where`: .deckhand/ or the folder the owner chose) when the script runs
    from the skill inside a Deckhand project, so a runbook command sees the same keys `dh` does. None otherwise."""
    try:
        skill = str(Path(__file__).resolve().parents[2])
        if skill not in sys.path:
            sys.path.insert(0, skill)
        from dhlib import profile as P
        from dhlib.util import project_root
        if P._PROJECT is None:
            P.use_project(project_root())
        return P.layer_dir()
    except Exception:  # noqa: BLE001 — a copied script keeps working on the machine vault
        return None


def resolve(url_override=None, token_override=None, env=None, home=None):
    """Resolve Coolify URL + token, or raise SystemExit('config error: ...')."""
    live = env is None
    env = os.environ if env is None else env
    home = Path(home) if home is not None else HOME
    url = url_override or env.get("COOLIFY_URL")
    token = token_override or env.get("COOLIFY_TOKEN")
    dk = env.get("DECKHAND_HOME") or (str(Path.home() / ".deckhand") if live else None)
    lay = project_layer() if live and (not url or not token) else None
    if lay:
        vault, prof = deckhand_config(lay)
        token = token or vault.get("COOLIFY_TOKEN")
        url = url or vault.get("COOLIFY_URL") or prof
    if dk and (not url or not token):
        vault, prof = deckhand_config(Path(dk))
        token = token or vault.get("COOLIFY_TOKEN")
        url = url or vault.get("COOLIFY_URL") or prof
    cfg_path = home / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(f"config error: cannot parse {cfg_path}: {exc}")
        url = url or cfg.get("coolify_url")
        token = token or cfg.get("coolify_token")
    if not token:
        secrets = home / "secrets" / "env.sh"
        if secrets.exists():
            for line in secrets.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("export COOLIFY_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not url or not token:
        raise SystemExit(
            "config error: need both Coolify URL and token — set COOLIFY_URL/COOLIFY_TOKEN, "
            "or `dh vault set COOLIFY_TOKEN` + `dh profile set coolify.url=…` (see references/ops/10-bootstrap-vps.md)"
        )
    return url.rstrip("/"), token


def build_request(url, token, method, path, params=None, body=None):
    full = url.rstrip("/") + "/api/v1" + path
    if params:
        full += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items() if v is not None})
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": "vps-ops/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(full, data=data, method=method, headers=headers)


def _http_req(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")


def api(url, token, method, path, params=None, body=None, timeout=60, http=None):
    http = http or _http_req
    req = build_request(url, token, method, path, params=params, body=body)
    status, raw = http(req, timeout)
    try:
        return status, (json.loads(raw) if raw.strip() else None)
    except ValueError:
        return status, raw


def _deployment_rows(body):
    """Normalize GET /deployments/applications/{uuid}.

    Live shape (Coolify 4.3.21): {"count": N, "deployments": [ {...}, ... ]}.
    Tolerates a plain list and {"data": [...]} wrappers too. Returns newest-first.
    """
    rows = []
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict):
        for key in ("deployments", "data"):
            if isinstance(body.get(key), list):
                rows = body[key]
                break
    rows = [r for r in rows if isinstance(r, dict)]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def wait_for_deploy(url, token, uuid, timeout=900, interval=10, api_fn=None,
                    sleep=time.sleep, now=time.time, log=print, expect_commit=None):
    """Poll the newest deployment for <uuid> until terminal status. Returns 0/3/5.

    With expect_commit set, a finished/failed deployment carrying a DIFFERENT commit is
    treated as stale (the push's build may not have registered yet) and polling continues
    until YOUR commit reaches a terminal state — or the timeout fires.
    """
    api_fn = api_fn or api
    t0 = now()
    while True:
        if now() - t0 > timeout:
            tail = f" — never saw a terminal deployment for commit {expect_commit}" if expect_commit else ""
            log(f"TIMEOUT after {timeout}s{tail}")
            return 5
        status, body = api_fn(url, token, "GET", f"/deployments/applications/{uuid}")
        rows = _deployment_rows(body)
        latest = rows[0] if rows else None
        if latest:
            st = str(latest.get("status", "")).lower()
            dep = latest.get("deployment_uuid") or latest.get("uuid") or "?"
            commit = str(latest.get("commit") or "")
            log(f"  [{int(now() - t0):>4}s] {st}" + (f" {commit}" if commit else ""))
            mine = (not expect_commit) or commit.startswith(expect_commit)
            if st in OK_STATUS:
                if not mine:
                    log(f"  finished {commit or '?'} != your {expect_commit} — stale deployment, still waiting for your build")
                else:
                    log(f"SUCCESS ({int(now() - t0)}s, deployment {dep}" + (f", commit {commit}" if commit else "") + ")")
                    return 0
            if st in FAIL_STATUS and mine:
                log(f"DEPLOY FAILED ({st}, deployment {dep})")
                return 3
        sleep(interval)


def _http_url(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "vps-ops/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200000).decode("utf-8", "ignore")


def smoke(target, expect=200, contains=None, timeout=30, http=None):
    http = http or _http_url
    try:
        status, text = http(target, timeout)
    except Exception as exc:
        print(f"FAIL {type(exc).__name__} {target} ({exc})")
        return 4
    ok = status == expect and (not contains or contains in text or contains in html.unescape(text))   # "L'Atelier" is &#x27; in HTML
    print(f"{'OK' if ok else 'FAIL'} {status} {target}")
    return 0 if ok else 4


# ----------------------------- tunnel -------------------------------------
# The dashboard is loopback-only on the VPS: every call goes through an ssh -L tunnel.
# `tunnel` health-checks and (when VPS_SSH_HOST/VPS_SSH_KEY are configured) starts the
# tunnel itself as a detached background process; `deploy` preflights it automatically.

def _url_port(url, default=8000):
    try:
        return urllib.parse.urlsplit(url).port or default
    except ValueError:
        return default


def tunnel_settings(env=None, home=None):
    """Resolve the SSH tunnel target from env > ~/.vps-ops/config.json. None if unset.

    Env/config keys: VPS_SSH_HOST (e.g. root@1.2.3.4), VPS_SSH_KEY (private key path),
    optional VPS_KNOWN_HOSTS (default <home>/ssh/known_hosts), VPS_DASH_PORT (remote, 8000).
    """
    env = os.environ if env is None else env
    home = Path(home) if home is not None else HOME
    host = env.get("VPS_SSH_HOST")
    key = env.get("VPS_SSH_KEY")
    if not host or not key:
        cfg_path = home / "config.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
            host = host or cfg.get("vps_ssh_host")
            key = key or cfg.get("vps_ssh_key")
    if not host or not key:
        return None
    return {
        "host": host,
        "key": key,
        "known_hosts": env.get("VPS_KNOWN_HOSTS") or str(home / "ssh" / "known_hosts"),
        "remote_port": int(env.get("VPS_DASH_PORT") or 8000),
    }


def tunnel_command(host, key, known_hosts, local_port=8000, remote_port=8000):
    return ["ssh", "-N", "-L", f"{local_port}:127.0.0.1:{remote_port}", "-i", key,
            "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", host]


def _health_ok(port, timeout=3):
    try:
        st, _body = _http_url(f"http://127.0.0.1:{port}/api/health", timeout)
        return st == 200
    except Exception:
        return False


def _spawn_detached(cmd):
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def ensure_tunnel(port=8000, log=print, wait=20, spawn=True, settings=None):
    """0 when 127.0.0.1:<port> answers (auto-starting the tunnel when configured), else 4."""
    if _health_ok(port):
        return 0
    t = settings or tunnel_settings()
    if not t:
        log("tunnel DOWN — VPS_SSH_HOST/VPS_SSH_KEY not set, cannot auto-start. Manual:")
        log('  ssh -N -L %d:127.0.0.1:8000 -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" '
            '-o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<VPS_IP>' % port)
        return 4
    cmd = tunnel_command(t["host"], t["key"], t["known_hosts"], port, t["remote_port"])
    if not spawn:
        log("tunnel DOWN. Run: " + " ".join(cmd))
        return 4
    try:
        _spawn_detached(cmd)
    except Exception as exc:
        log(f"tunnel spawn failed ({exc}). Run manually: " + " ".join(cmd))
        return 4
    for _ in range(int(wait)):
        time.sleep(1)
        if _health_ok(port):
            log("tunnel was down — started it (detached ssh).")
            return 0
    log("tunnel spawned but /api/health still failing — check the key + known_hosts. Manual: " + " ".join(cmd))
    return 4


# ----------------------------- subcommands -------------------------------

def cmd_health(a, url, token):
    st, body = api(url, token, "GET", "/health", timeout=15)
    tail = "" if st == 200 else f" — {str(body)[:200]}"
    print(f"coolify health: {st}{tail}")
    return 0 if st == 200 else 4


def cmd_apps(a, url, token):
    st, body = api(url, token, "GET", "/applications")
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    for app in body or []:
        print(f"{app.get('uuid', '?'):<28} {str(app.get('name', '?')):<28} {app.get('status', '?')}")
    return 0


def cmd_app(a, url, token):
    st, body = api(url, token, "GET", f"/applications/{a.uuid}")
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    print(json.dumps(body, indent=1)[:4000])
    return 0


def cmd_deploy(a, url, token):
    rc = ensure_tunnel(_url_port(url))
    if rc != 0:
        return rc
    params = {"uuid": a.uuid}
    if a.force:
        params["force"] = "true"
    st, body = api(url, token, "POST", "/deploy", params=params)
    print(f"deploy {a.uuid}: HTTP {st} {str(body)[:300] if body else ''}")
    return 0 if st in (200, 201) else 4


def cmd_deployments(a, url, token):
    st, body = api(url, token, "GET", f"/deployments/applications/{a.uuid}")
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    rows = _deployment_rows(body)
    for d in rows[: a.limit]:
        dep = d.get("deployment_uuid") or d.get("uuid") or "?"
        print(f"{str(d.get('status', '?')):<12} {str(d.get('created_at', ''))[:19]:<20} {dep}")
    if not rows:
        print("(no deployments yet)")
    return 0


def cmd_wait(a, url, token):
    return wait_for_deploy(url, token, a.uuid, timeout=a.timeout, interval=a.interval,
                           expect_commit=a.expect_commit)


def cmd_logs(a, url, token):
    st, body = api(url, token, "GET", f"/applications/{a.uuid}/logs",
                   params={"lines": a.lines, "show_timestamps": "true" if a.timestamps else None})
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    if isinstance(body, dict):
        body = body.get("logs", body)
    print(str(body)[:8000])
    return 0


def cmd_dlogs(a, url, token):
    st, body = api(url, token, "GET", f"/deployments/applications/{a.uuid}")
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    rows = _deployment_rows(body)
    if not rows:
        print("(no deployments yet)")
        return 4
    dep = rows[0]
    if a.deployment:
        dep = next((d for d in rows
                    if a.deployment in (str(d.get("deployment_uuid") or ""), str(d.get("uuid") or ""))), None)
        if dep is None:
            print(f"deployment not found: {a.deployment}")
            return 4
    logs = dep.get("logs") or ""
    text = str(logs)
    try:
        entries = json.loads(logs) if isinstance(logs, str) else logs
        if isinstance(entries, list):
            text = "\n".join(str(e.get("output")) for e in entries
                             if isinstance(e, dict) and e.get("output"))
    except (ValueError, TypeError):
        pass
    lines = text.splitlines()
    if a.grep:
        lines = [ln for ln in lines if a.grep in ln]
    print(f"deployment {dep.get('deployment_uuid') or dep.get('uuid')} | {dep.get('status')} | "
          f"{str(dep.get('created_at'))[:19]} | commit {str(dep.get('commit'))[:12]}")
    if not lines:
        print("(no matching log lines)")
        return 0
    for ln in (lines[-a.tail:] if a.tail > 0 else lines):
        print(ln)
    return 0


def cmd_envs(a, url, token):
    st, body = api(url, token, "GET", f"/applications/{a.uuid}/envs")
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    for e in body or []:
        print(e.get("key"))
    return 0


def env_pairs(pairs=(), file=None):
    """KEY=VALUE from the arguments (non-secrets) and/or a dotenv file (secrets: never on a command line)."""
    lines = list(pairs)
    if file:
        lines += [ln for ln in Path(file).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    data = []
    for pair in lines:
        pair = pair.strip()
        if pair.startswith("export "):
            pair = pair[len("export "):]
        if "=" not in pair:
            raise ValueError(f"bad line (need KEY=VALUE): {pair.split('=')[0][:40]}")
        k, v = pair.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        data.append({"key": k.strip(), "value": v})
    return data


def cmd_envset(a, url, token):
    try:
        data = env_pairs(a.pairs, getattr(a, "file", None))
    except (ValueError, OSError) as e:
        print(str(e))
        return 4
    if not data:
        print("nothing to set: KEY=VALUE (non-secret) or --file .env.production")
        return 4
    st, body = api(url, token, "PATCH", f"/applications/{a.uuid}/envs/bulk", body={"data": data})
    print(f"envset {a.uuid}: HTTP {st} — keys: {', '.join(d['key'] for d in data)}")   # never the values
    return 0 if 200 <= st < 300 else 4


def cmd_status(a, url, token):
    st, apps = api(url, token, "GET", "/applications")
    if st != 200:
        print(f"error {st}: {str(apps)[:300]}")
        return 4
    for app in apps or []:
        s2, deps = api(url, token, "GET", f"/deployments/applications/{app['uuid']}")
        rows = _deployment_rows(deps)
        last = rows[0] if rows else {}
        print(f"{str(app.get('name', '?')):<28} {str(app.get('status', '?')):<10} "
              f"last:{str(last.get('status', '-')):<10} {str(last.get('created_at', ''))[:19]}")
    return 0


def cmd_smoke(a):
    return smoke(a.target, expect=a.expect, contains=a.contains)


def cmd_tunnel(a, url, token):
    port = a.port or _url_port(url)
    if _health_ok(port):
        print(f"tunnel OK (127.0.0.1:{port})")
        return 0
    return ensure_tunnel(port, wait=a.wait)


def main(argv=None):
    p = argparse.ArgumentParser(prog="coolify_api.py", description="deckhand Coolify client")
    p.add_argument("--url")
    p.add_argument("--token")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, cfg=True):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn, needs_cfg=cfg)
        return sp

    add("health", cmd_health)
    add("apps", cmd_apps)
    sp = add("app", cmd_app); sp.add_argument("uuid")
    sp = add("deploy", cmd_deploy); sp.add_argument("uuid"); sp.add_argument("--force", action="store_true")
    sp = add("deployments", cmd_deployments); sp.add_argument("uuid"); sp.add_argument("--limit", type=int, default=10)
    sp = add("wait", cmd_wait); sp.add_argument("uuid")
    sp.add_argument("--timeout", type=int, default=900); sp.add_argument("--interval", type=int, default=10); sp.add_argument("--expect-commit", default=None)
    sp = add("logs", cmd_logs); sp.add_argument("uuid")
    sp.add_argument("--lines", type=int, default=200); sp.add_argument("--timestamps", action="store_true")
    sp = add("dlogs", cmd_dlogs); sp.add_argument("uuid"); sp.add_argument("--deployment", default=None)
    sp.add_argument("--grep", default=None); sp.add_argument("--tail", type=int, default=120)
    sp = add("envs", cmd_envs); sp.add_argument("uuid")
    sp = add("envset", cmd_envset); sp.add_argument("uuid"); sp.add_argument("pairs", nargs="*"); sp.add_argument("--file", help="a dotenv file: the way for secrets")
    add("status", cmd_status)
    sp = add("tunnel", cmd_tunnel); sp.add_argument("--port", type=int, default=0); sp.add_argument("--wait", type=int, default=20)
    sp = add("smoke", cmd_smoke, cfg=False); sp.add_argument("target")
    sp.add_argument("--expect", type=int, default=200); sp.add_argument("--contains")

    a = p.parse_args(argv)
    try:
        if getattr(a, "needs_cfg", False):
            url, token = resolve(a.url, a.token)
            return a.fn(a, url, token)
        return a.fn(a)
    except SystemExit:
        raise
    except Exception as e:
        msg = str(e)
        if isinstance(e, urllib.error.URLError) and ("10061" in msg or "refused" in msg.lower()):
            print("CONNECTION REFUSED — the Coolify dashboard tunnel is dead (this is the tunnel, not Coolify).")
            print("Try: py ops/scripts/coolify_api.py tunnel   (health-checks and auto-starts it when VPS_SSH_HOST/VPS_SSH_KEY are set)")
            print("Or restart it as a BACKGROUND process, then re-run:")
            print('  ssh -N -o ExitOnForwardFailure=yes -L 8000:127.0.0.1:8000 -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<VPS_IP>')
            print("  curl -s http://127.0.0.1:8000/api/health   # expect OK")
            return 6
        print(f"unexpected error: {type(e).__name__}: {e}")
        return 6


if __name__ == "__main__":
    sys.exit(main())
