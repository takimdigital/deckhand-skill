import json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import coolify_api as ca  # noqa: E402


def make_http(status=200, body=""):
    calls = []

    def _f(req, timeout):
        calls.append(req)
        return status, body

    _f.calls = calls
    return _f


def _dep(status, created="2026-09-17T00:00:00Z", uuid="d1"):
    return {"status": status, "created_at": created, "deployment_uuid": uuid}


class ResolveTests(unittest.TestCase):
    def test_env_beats_config__config_fills__missing_is_loud(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(json.dumps({"coolify_url": "http://cfg:8000", "coolify_token": "cfg-tok"}), encoding="utf-8")
            # env wins over config
            url, tok = ca.resolve(env={"COOLIFY_URL": "http://env:8000", "COOLIFY_TOKEN": "env-tok"}, home=td)
            self.assertEqual((url, tok), ("http://env:8000", "env-tok"))
            # config fills when env empty
            url, tok = ca.resolve(env={}, home=td)
            self.assertEqual((url, tok), ("http://cfg:8000", "cfg-tok"))
        # nothing anywhere -> loud config error
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit) as cm:
                ca.resolve(env={}, home=td)
            self.assertTrue(str(cm.exception).startswith("config error:"))

    def test_secrets_file_supplies_token(self):
        with tempfile.TemporaryDirectory() as td:
            sec = Path(td) / "secrets"
            sec.mkdir()
            (sec / "env.sh").write_text('export COOLIFY_TOKEN="tok-from-file"\n', encoding="utf-8")
            url, tok = ca.resolve(url_override="http://x:8000", env={}, home=td)
            self.assertEqual(tok, "tok-from-file")

    def test_flags_beat_everything(self):
        url, tok = ca.resolve(url_override="http://flag:8000", token_override="flag-tok",
                              env={"COOLIFY_URL": "http://env:8000", "COOLIFY_TOKEN": "env-tok"})
        self.assertEqual((url, tok), ("http://flag:8000", "flag-tok"))


class RequestTests(unittest.TestCase):
    def test_build_request_url_headers_params(self):
        req = ca.build_request("http://h:8000/", "tok", "POST", "/deploy",
                               params={"uuid": "abc", "force": "false"})
        self.assertEqual(req.full_url, "http://h:8000/api/v1/deploy?uuid=abc&force=false")
        self.assertEqual(req.get_header("Authorization"), "Bearer tok")
        self.assertEqual(req.method, "POST")

    def test_api_parses_json_and_error_text(self):
        http = make_http(200, '{"ok": true}')
        st, body = ca.api("http://h:8000", "tok", "GET", "/health", http=http)
        self.assertEqual((st, body), (200, {"ok": True}))
        http = make_http(500, "not json at all")
        st, body = ca.api("http://h:8000", "tok", "GET", "/nope", http=http)
        self.assertEqual(st, 500)
        self.assertEqual(body, "not json at all")

    def test_api_json_body_and_content_type(self):
        http = make_http(201, "{}")
        ca.api("http://h:8000", "tok", "POST", "/projects", body={"name": "demo"}, http=http)
        req = http.calls[0]
        self.assertEqual(json.loads(req.data.decode()), {"name": "demo"})
        self.assertEqual(req.get_header("Content-type"), "application/json")


class DeploymentRowsTests(unittest.TestCase):
    """Live shape (2026-09-17, Coolify 4.3.21): {"count": N, "deployments": [...]}."""

    def test_wrapped_dict(self):
        rows = ca._deployment_rows({"count": 1, "deployments": [_dep("finished")]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "finished")

    def test_plain_list_and_other_wrappers(self):
        self.assertEqual(len(ca._deployment_rows([_dep("failed")])), 1)
        self.assertEqual(len(ca._deployment_rows({"data": [_dep("queued")]})), 1)
        self.assertEqual(ca._deployment_rows(None), [])
        self.assertEqual(ca._deployment_rows({}), [])

    def test_newest_first_by_created_at(self):
        rows = ca._deployment_rows({"deployments": [
            _dep("queued", "2026-09-17T00:00:00Z", "old"),
            _dep("finished", "2026-09-18T00:19:31Z", "new"),
        ]})
        self.assertEqual(rows[0]["deployment_uuid"], "new")


class WaitTests(unittest.TestCase):
    def _runner(self, statuses, timeout=900, wrap=True):
        seq = list(statuses)

        def fake_api(url, token, method, path, params=None, body=None, timeout=60, http=None):
            st = seq.pop(0) if seq else statuses[-1]
            if st is None:
                payload = {"count": 0, "deployments": []} if wrap else []
            else:
                item = _dep(st)
                payload = {"count": 1, "deployments": [item]} if wrap else [item]
            return 200, payload

        clock = {"t": 0.0}

        def now():
            clock["t"] += 5.0
            return clock["t"]

        return ca.wait_for_deploy("http://h:8000", "tok", "app-uuid", timeout=timeout, interval=1,
                                  api_fn=fake_api, sleep=lambda s: None, now=now, log=lambda *a: None)

    def test_transient_empty_then_success_wrapped(self):
        self.assertEqual(self._runner([None, "queued", "in_progress", "finished"]), 0)

    def test_success_failed_timeout(self):
        self.assertEqual(self._runner(["finished"]), 0)
        self.assertEqual(self._runner(["queued", "failed"]), 3)
        self.assertEqual(self._runner(["queued", "queued", "queued"], timeout=12), 5)

    def test_plain_list_shape_still_supported(self):
        self.assertEqual(self._runner(["queued", "success"], wrap=False), 0)


class SmokeTests(unittest.TestCase):
    def test_smoke_pass_fail_and_marker(self):
        ok = lambda url, timeout: (200, "hello world")
        self.assertEqual(ca.smoke("https://x", http=ok), 0)
        bad = lambda url, timeout: (500, "err")
        self.assertEqual(ca.smoke("https://x", http=bad), 4)
        self.assertEqual(ca.smoke("https://x", contains="missing", http=ok), 4)
        self.assertEqual(ca.smoke("https://x", contains="hello", http=ok), 0)

    def test_smoke_connection_error_is_4(self):
        def boom(url, timeout):
            raise OSError("connection refused")

        self.assertEqual(ca.smoke("https://x", http=boom), 4)


class CmdDeploymentsTests(unittest.TestCase):
    def test_cmd_deployments_wrapped_no_crash(self):
        with mock.patch.object(ca, "api", return_value=(200, {"count": 1, "deployments": [_dep("finished")]})):
            rc = ca.cmd_deployments(SimpleNamespace(uuid="u", limit=5), "http://x", "t")
        self.assertEqual(rc, 0)

    def test_cmd_deployments_empty(self):
        with mock.patch.object(ca, "api", return_value=(200, {"count": 0, "deployments": []})):
            rc = ca.cmd_deployments(SimpleNamespace(uuid="u", limit=5), "http://x", "t")
        self.assertEqual(rc, 0)


class CmdEnvsetTests(unittest.TestCase):
    def test_envset_accepts_201(self):
        with mock.patch.object(ca, "api", return_value=(201, [{"key": "A"}])):
            rc = ca.cmd_envset(SimpleNamespace(uuid="u", pairs=["A=B"]), "http://x", "t")
        self.assertEqual(rc, 0)


class TunnelTests(unittest.TestCase):
    HOME_NX = "Z:/deckhand-no-home"

    def test_tunnel_command_shape(self):
        cmd = ca.tunnel_command("root@1.2.3.4", "C:/k/id_ed25519", "C:/k/known_hosts", 8010, 8000)
        self.assertEqual(cmd[:3], ["ssh", "-N", "-L"])
        self.assertIn("8010:127.0.0.1:8000", cmd)
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("StrictHostKeyChecking=yes", cmd)
        self.assertEqual(cmd[-1], "root@1.2.3.4")

    def test_tunnel_settings_from_env(self):
        t = ca.tunnel_settings(env={"VPS_SSH_HOST": "root@x", "VPS_SSH_KEY": "C:/k"},
                               home=self.HOME_NX)
        self.assertEqual(t["host"], "root@x")
        self.assertEqual(t["key"], "C:/k")
        self.assertTrue(t["known_hosts"].endswith("known_hosts"))
        self.assertEqual(t["remote_port"], 8000)

    def test_tunnel_settings_unconfigured_is_none(self):
        self.assertIsNone(ca.tunnel_settings(env={}, home=self.HOME_NX))

    def test_ensure_tunnel_spawns_once_and_waits(self):
        state = {"n": 0}
        spawned = []

        def health(port, timeout=3):
            state["n"] += 1
            return state["n"] > 1  # down first, up after the "spawn"

        with mock.patch.object(ca, "_health_ok", health), \
             mock.patch.object(ca, "_spawn_detached", lambda cmd: spawned.append(cmd)), \
             mock.patch.object(ca.time, "sleep", lambda s: None):
            rc = ca.ensure_tunnel(8000, log=lambda *a, **k: None,
                                  settings={"host": "root@x", "key": "k",
                                            "known_hosts": "kh", "remote_port": 8000})
        self.assertEqual(rc, 0)
        self.assertEqual(len(spawned), 1)

    def test_ensure_tunnel_healthy_is_silent(self):
        with mock.patch.object(ca, "_health_ok", lambda port, timeout=3: True):
            self.assertEqual(ca.ensure_tunnel(8000, log=lambda *a, **k: None), 0)


class WaitCommitTests(unittest.TestCase):
    def test_wait_skips_stale_finished_then_matches(self):
        seq = [
            {"deployments": [{"status": "finished", "commit": "aaaaaaa", "deployment_uuid": "d1",
                              "created_at": "2026-09-20T01:00:00"}]},
            {"deployments": [{"status": "finished", "commit": "bbbbbbb", "deployment_uuid": "d2",
                              "created_at": "2026-09-20T02:00:00"}]},
        ]
        calls = {"i": 0}

        def api_fn(url, token, method, path):
            i = min(calls["i"], len(seq) - 1)
            calls["i"] += 1
            return 200, seq[i]

        times = iter(range(0, 20))
        logs = []
        rc = ca.wait_for_deploy("http://x", "t", "u", timeout=100, interval=0, api_fn=api_fn,
                                sleep=lambda s: None, now=lambda: next(times),
                                log=lambda *a: logs.append(" ".join(str(x) for x in a)),
                                expect_commit="bbb")
        self.assertEqual(rc, 0)
        self.assertEqual(calls["i"], 2)
        self.assertTrue(any("SUCCESS" in ln for ln in logs))

    def test_wait_without_expect_commit_unchanged(self):
        row = {"deployments": [{"status": "finished", "commit": "aaaaaaa", "deployment_uuid": "d1",
                                "created_at": "2026-09-20T01:00:00"}]}

        def api_fn(url, token, method, path):
            return 200, row

        times = iter(range(0, 10))
        rc = ca.wait_for_deploy("http://x", "t", "u", timeout=100, interval=0, api_fn=api_fn,
                                sleep=lambda s: None, now=lambda: next(times),
                                log=lambda *a: None)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
