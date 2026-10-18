#!/usr/bin/env python3
"""Thin Hostinger API client (stdlib only) — used by the ops runbooks (references/ops/10 and 20).

Token: HOSTINGER_API_TOKEN env or --token. Base URL: https://developers.hostinger.com
Schemas pinned from the official OpenAPI spec (github.com/hostinger/api).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://developers.hostinger.com"
DEFAULT_KEY_FILE = str(Path.home() / ".vps-ops" / "ssh" / "id_ed25519.pub")


def build_request(token, method, path, params=None, body=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items() if v is not None})
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": "vps-ops/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=data, method=method, headers=headers)


def _http_call(method, url, token, body=None, timeout=60, params=None):
    if params:
        sep = "&" if "?" in url else "?"
        url += sep + urllib.parse.urlencode({k: str(v) for k, v in params.items() if v is not None})
    req = urllib.request.Request(
        url,
        data=(json.dumps(body).encode("utf-8") if body is not None else None),
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                 "Content-Type": "application/json", "User-Agent": "vps-ops/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "ignore")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:400]


def _items(body):
    if isinstance(body, dict):
        for key in ("data", "items"):
            if isinstance(body.get(key), list):
                return body[key]
        return [body]
    return body or []


def a_entries(names, ip, ttl=14400):
    return [{"name": n, "type": "A", "ttl": ttl, "records": [{"content": ip}]} for n in names]


def update_payload(names, ip, ttl=14400):
    # overwrite=true scoped to the name+type entries we send: exact desired state for those A names,
    # every other record (MX/TXT/other names) is untouched. See references/ops/20-domain-dns-ssl.md.
    return {"overwrite": True, "zone": a_entries(names, ip, ttl)}


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


def _vault_token():
    """HOSTINGER_API_TOKEN from this project's vault, the deckhand vault, else v1's ~/.vps-ops/secrets/env.sh."""
    import shlex
    dk = Path(os.environ.get("DECKHAND_HOME") or (Path.home() / ".deckhand"))
    legacy = Path(os.environ.get("VPS_OPS_HOME") or (Path.home() / ".vps-ops")) / "secrets" / "env.sh"
    lay = project_layer()
    for f in ([lay / "vault.env"] if lay else []) + [dk / "vault.env", legacy]:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                k, _, v = line.replace("export ", "", 1).partition("=")
                if k.strip() == "HOSTINGER_API_TOKEN" and v.strip():
                    try:
                        return shlex.split(v.strip())[0]
                    except (ValueError, IndexError):
                        return v.strip().strip("'\"")
    return None


def ensure_key(token, key_material, vm_id, name="vps-ops", http=None):
    """Idempotent: register the key on the account if missing, then attach it to the VM. 0 = ok."""
    http = http or _http_call
    st, body = http("GET", BASE + "/api/vps/v1/public-keys", token, None)
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    key_id = None
    for item in _items(body):
        if not isinstance(item, dict):
            continue
        for field in ("key", "public_key", "content"):
            got = item.get(field)
            if got and str(got).strip().strip('"') == str(key_material).strip():
                key_id = item.get("id")
                break
        if key_id is not None:
            break
    if key_id is None:
        st, body = http("POST", BASE + "/api/vps/v1/public-keys", token,
                        {"name": name, "key": key_material})
        if st not in (200, 201):
            print(f"error {st}: {str(body)[:300]}")
            return 4
        key_id = (body or {}).get("id")
    st, body = http("POST", f"{BASE}/api/vps/v1/public-keys/attach/{vm_id}", token, {"ids": [key_id]})
    if st not in (200, 201):
        print(f"error {st}: {str(body)[:300]}")
        return 4
    print(f"ssh key {key_id} attached to vm {vm_id}")
    return 0


def dns_set_a(token, domain, ip, names, ttl=14400, http=None):
    """Validate then PUT the A records (overwrite=true scoped). 0 = ok."""
    http = http or _http_call
    payload = update_payload(names, ip, ttl)
    st, body = http("POST", f"{BASE}/api/dns/v1/zones/{domain}/validate", token, payload)
    if st != 200:
        print(f"dns validate failed {st}: {str(body)[:400]}")
        return 4
    st, body = http("PUT", f"{BASE}/api/dns/v1/zones/{domain}", token, payload)
    if st != 200:
        print(f"dns update failed {st}: {str(body)[:400]}")
        return 4
    print(f"dns updated: {', '.join(f'{n} A {ip}' for n in names)} (ttl {ttl})")
    return 0


def firewall_ensure(token, vm_id, name="vps-ops", ports="22,80,443,8000,6001,6002", http=None):
    """Idempotent: create the firewall group if missing, add accept rules, sync, activate. 0 = ok."""
    http = http or _http_call
    st, body = http("GET", BASE + "/api/vps/v1/firewall", token, None)
    if st != 200:
        print(f"error {st}: {str(body)[:300]}")
        return 4
    fw = next((x for x in _items(body) if isinstance(x, dict) and x.get("name") == name), None)
    if fw is None:
        st, body = http("POST", BASE + "/api/vps/v1/firewall", token, {"name": name})
        if st not in (200, 201):
            print(f"error {st}: {str(body)[:300]}")
            return 4
        fw = body
        for port in [p.strip() for p in ports.split(",") if p.strip()]:
            st, rb = http("POST", f"{BASE}/api/vps/v1/firewall/{fw['id']}/rules", token,
                          {"protocol": "TCP", "port": port, "source": "any", "source_detail": "any"})
            if st not in (200, 201):
                print(f"rule {port} failed {st}: {str(rb)[:200]}")
                return 4
        print(f"firewall '{name}' created with ports {ports}")
    else:
        print(f"firewall '{name}' already exists (id {fw.get('id')}) — skipping rule creation")
    http("POST", f"{BASE}/api/vps/v1/firewall/{fw['id']}/sync", token, None)
    st, body = http("POST", f"{BASE}/api/vps/v1/firewall/{fw['id']}/activate/{vm_id}", token, None)
    if st not in (200, 201):
        print(f"activate failed {st}: {str(body)[:300]}")
        return 4
    print(f"firewall '{name}' synced + activated on vm {vm_id}")
    return 0


# ----------------------------- subcommands -------------------------------

def run_vm(token, a):
    if a.vm_cmd == "list":
        st, body = _http_call("GET", BASE + "/api/vps/v1/virtual-machines", token)
        if st != 200:
            print(f"error {st}: {str(body)[:300]}"); return 4
        for vm in _items(body):
            print(f"{vm.get('id', '?'):<10} {str(vm.get('state', '?')):<12} "
                  f"{vm.get('ipv4') or vm.get('ip') or '?':<16} {vm.get('hostname', '')}")
        return 0
    if a.vm_cmd == "get":
        st, body = _http_call("GET", f"{BASE}/api/vps/v1/virtual-machines/{a.id}", token)
        print(json.dumps(body, indent=1)[:4000]); return 0 if st == 200 else 4
    if a.vm_cmd == "metrics":
        now = datetime.now(timezone.utc)
        frm = now - timedelta(days=a.days)
        st, body = _http_call("GET", f"{BASE}/api/vps/v1/virtual-machines/{a.id}/metrics", token,
                              params={"date_from": frm.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                      "date_to": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
        if st != 200:
            print(f"error {st}: {str(body)[:300]}")
            return 4
        for series in ("cpu_usage", "ram_usage", "disk_space", "uptime"):
            s = (body or {}).get(series) or {}
            usage = s.get("usage") or {}
            if usage:
                last_key = sorted(usage.keys(), key=str)[-1]
                print(f"{series:<16} {usage[last_key]} {s.get('unit', '')} (at {last_key})")
        return 0
    if a.vm_cmd == "restart":
        st, body = _http_call("POST", f"{BASE}/api/vps/v1/virtual-machines/{a.id}/restart", token)
        print(f"restart vm {a.id}: HTTP {st} {str(body)[:200]}"); return 0 if st in (200, 201) else 4
    return 4


def main(argv=None):
    p = argparse.ArgumentParser(prog="hostinger_api.py", description="deckhand Hostinger client")
    p.add_argument("--token")
    sub = p.add_subparsers(dest="cmd", required=True)

    vm = sub.add_parser("vm").add_subparsers(dest="vm_cmd", required=True)
    vm.add_parser("list")
    g = vm.add_parser("get"); g.add_argument("id")
    m = vm.add_parser("metrics"); m.add_argument("id"); m.add_argument("--days", type=int, default=7)
    r = vm.add_parser("restart"); r.add_argument("id")

    sn = sub.add_parser("snapshot").add_subparsers(dest="sn_cmd", required=True)
    sc = sn.add_parser("create"); sc.add_argument("id")
    sl = sn.add_parser("list"); sl.add_argument("id")

    sk = sub.add_parser("sshkey").add_subparsers(dest="sk_cmd", required=True)
    ke = sk.add_parser("ensure")
    ke.add_argument("--vm", type=int, required=True)
    ke.add_argument("--name", default="vps-ops")
    ke.add_argument("--key-file", default=DEFAULT_KEY_FILE)

    dns = sub.add_parser("dns").add_subparsers(dest="dns_cmd", required=True)
    dg = dns.add_parser("get"); dg.add_argument("domain"); dg.add_argument("--save")
    ds = dns.add_parser("set-a"); ds.add_argument("domain"); ds.add_argument("--ip", required=True)
    ds.add_argument("--names", default="@,www"); ds.add_argument("--ttl", type=int, default=14400)

    fw = sub.add_parser("firewall").add_subparsers(dest="fw_cmd", required=True)
    fe = fw.add_parser("ensure"); fe.add_argument("--vm", type=int, required=True)
    fe.add_argument("--name", default="vps-ops"); fe.add_argument("--ports", default="22,80,443,8000,6001,6002")

    ac = sub.add_parser("actions"); ac.add_argument("vm"); ac.add_argument("action_id", nargs="?")

    a = p.parse_args(argv)
    token = a.token or os.environ.get("HOSTINGER_API_TOKEN") or _vault_token()
    if not token:
        raise SystemExit("config error: `dh vault set HOSTINGER_API_TOKEN` (or set the env var, or pass --token)")

    if a.cmd == "vm":
        return run_vm(token, a)
    if a.cmd == "snapshot":
        if a.sn_cmd == "create":
            st, body = _http_call("POST", f"{BASE}/api/vps/v1/virtual-machines/{a.id}/snapshot", token)
            print(f"snapshot vm {a.id}: HTTP {st} {str(body)[:200]}"); return 0 if st in (200, 201) else 4
        st, body = _http_call("GET", f"{BASE}/api/vps/v1/virtual-machines/{a.id}/snapshot", token)
        print(json.dumps(body, indent=1)[:2000]); return 0 if st == 200 else 4
    if a.cmd == "sshkey":
        key = Path(a.key_file).read_text(encoding="utf-8").strip()
        return ensure_key(token, key, a.vm, name=a.name)
    if a.cmd == "dns":
        if a.dns_cmd == "get":
            st, body = _http_call("GET", f"{BASE}/api/dns/v1/zones/{a.domain}", token)
            text = json.dumps(body, indent=1)
            if a.save:
                Path(a.save).write_text(text, encoding="utf-8")
                print(f"saved zone to {a.save}")
            print(text[:4000]); return 0 if st == 200 else 4
        return dns_set_a(token, a.domain, a.ip, [n.strip() for n in a.names.split(",") if n.strip()], a.ttl)
    if a.cmd == "firewall":
        return firewall_ensure(token, a.vm, name=a.name, ports=a.ports)
    if a.cmd == "actions":
        path = f"/api/vps/v1/virtual-machines/{a.vm}/actions"
        if a.action_id:
            path += f"/{a.action_id}"
        st, body = _http_call("GET", BASE + path, token)
        print(json.dumps(body, indent=1)[:3000]); return 0 if st == 200 else 4
    return 6


if __name__ == "__main__":
    sys.exit(main())
