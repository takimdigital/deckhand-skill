"""Where a project keeps its settings and keys: chosen once per project, remembered in .deckhand/layout.json.

Each project gets its own profile, vault and notes (`here`, the default the first write records, then asks the owner
once), or shares the machine's (`machine`, as before), or uses a folder outside the project. Reads always merge the
machine layer under the project's. The owner's own facts stay on the machine, so no project asks them again. A broken
choice (a missing folder, a copied project) refuses to write instead of splitting the keys; nothing in it is pushed.
"""
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(SKILL / "ops" / "scripts"))

from dhlib import profile, resume  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()          # Windows: RUNNER~1 → runneradmin, as the code resolves it
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "VPS_OPS_HOME", "COOLIFY_TOKEN", "COOLIFY_URL", "HOSTINGER_API_TOKEN", "CLOUDFLARE_API_TOKEN", "RESEND_API_KEY")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ["VPS_OPS_HOME"] = str(self.tmp / "vps-ops")
        for k in ("COOLIFY_TOKEN", "COOLIFY_URL", "HOSTINGER_API_TOKEN", "CLOUDFLARE_API_TOKEN", "RESEND_API_KEY"):
            os.environ.pop(k, None)
        self.a, self.b = self.tmp / "shop-a", self.tmp / "shop-b"
        profile.use_project(None)

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        profile.use_project(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dh(self, root, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])

    def project(self, root, *extra):
        root.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.dh(root, "init", "--name", root.name, *extra)[0], 0)
        return root

    def machine(self, name="profile.json"):
        return Path(os.environ["DECKHAND_HOME"]) / name


class FirstUse(Base):
    def test_the_first_project_write_keeps_it_in_the_project_and_asks_once_then_never_again(self):
        self.project(self.a)
        self.assertFalse((self.a / ".deckhand" / "layout.json").exists(), "dh init chooses nothing")
        code, out = self.dh(self.a, "profile", "where")
        self.assertIsNone(out["location"])
        self.assertIn("not chosen yet", out["say"])
        code, out = self.dh(self.a, "profile", "set", "domain.default=shop-a.com")
        self.assertEqual((code, out["scope"]), (0, "project"))
        self.assertEqual(Path(out["path"]), self.a / ".deckhand" / "profile.json")
        self.assertIn("dh profile where --set machine", out["ask_once"])
        self.assertEqual(out["bound"]["location"], "here")
        lay = json.loads((self.a / ".deckhand" / "layout.json").read_text(encoding="utf-8"))
        self.assertEqual((lay["location"], lay["chosen_by"], Path(lay["root"])), ("here", "default", self.a.resolve()))
        for k in ("profile_path", "vault_path", "profile_md_path", "bound_at"):
            self.assertIn(k, lay)
        self.assertFalse(self.machine().exists(), "nothing reached the machine layer")
        code, out = self.dh(self.a, "profile", "set", "email.provider=resend")      # same project: silent
        self.assertNotIn("ask_once", out)
        self.assertEqual(out["scope"], "project")
        self.assertIn("default, the owner has not chosen", (self.a / ".deckhand" / "RESUME.md").read_text(encoding="utf-8"))

    def test_the_owners_own_facts_stay_on_the_machine_so_no_project_asks_them_again(self):
        self.project(self.a)
        self.project(self.b)
        code, out = self.dh(self.a, "profile", "set", "owner.name=Hakim", "defaults.hosting=vps")
        self.assertEqual(out["scope"], "machine")
        self.assertNotIn("ask_once", out)
        self.assertFalse((self.a / ".deckhand" / "layout.json").exists(), "the owner's facts choose nothing for the project")
        code, out = self.dh(self.a, "profile", "set", "owner.timezone=Africa/Casablanca", "domain.default=a.com")
        self.assertEqual(out["split"], {"machine": ["owner.timezone"], "project": ["domain.default"]})
        self.assertIn("ask_once", out)
        code, out = self.dh(self.b, "profile", "show")
        self.assertEqual(out["profile"]["owner"]["name"], "Hakim")                  # project B inherits the owner
        self.assertNotIn("domain", out["profile"])                                   # but not project A's domain
        code, out = self.dh(self.a, "profile", "doctor", "--offline")
        self.assertNotIn("owner.name", out["missing_fields"])
        self.assertEqual(out["where"]["location"], "here")
        self.assertTrue(out["project_layer"].endswith("profile.json"))

    def test_each_project_has_its_own_vault_and_the_machine_vault_stays_a_fallback(self):
        self.project(self.a)
        self.project(self.b)
        profile.use_project(self.a)
        out = profile.vault_set("RESEND_API_KEY", "re_shop_a_value_111")
        self.assertEqual(out["scope"], "project")
        self.assertIn("ask_once", out)
        self.assertEqual(profile.vault_set("CLOUDFLARE_API_TOKEN", "machine-wide-cf-222", where="machine")["scope"], "machine")
        self.assertEqual(profile.secret("RESEND_API_KEY"), "re_shop_a_value_111")
        profile.use_project(self.b)
        self.assertIsNone(profile.secret("RESEND_API_KEY"), "project A's key is invisible in project B")
        self.assertEqual(profile.secret("CLOUDFLARE_API_TOKEN"), "machine-wide-cf-222")
        self.assertNotIn("re_shop_a_value_111", self.machine("vault.env").read_text(encoding="utf-8"))
        if os.name != "nt":
            self.assertEqual(oct(os.stat(self.a / ".deckhand" / "vault.env").st_mode)[-3:], "600")
        code, out = self.dh(self.a, "vault", "list")
        self.assertEqual(out["by_layer"], {"machine": ["CLOUDFLARE_API_TOKEN"], "project": ["RESEND_API_KEY"]})
        self.assertNotIn("re_shop_a_value_111", json.dumps(out))
        # the shell line loads both, the project's last (it wins), and prints paths, never values
        profile.use_project(None)
        profile.vault_set("RESEND_API_KEY", "machine-value-333", where="machine")
        code, out = self.dh(self.a, "vault", "list")
        self.assertNotIn("machine-value-333", out["shell"])
        if shutil.which("bash") and os.name != "nt":
            r = subprocess.run(["bash", "-c", out["shell"] + '; printf %s "$RESEND_API_KEY"'], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.stdout, "re_shop_a_value_111")


class Choose(Base):
    def test_two_projects_two_choices_each_remembered(self):
        self.project(self.a)
        self.project(self.b)
        code, out = self.dh(self.b, "profile", "where", "--set", "machine")
        self.assertEqual((code, out["location"], out["chosen_by"]), (0, "machine", "owner"))
        code, out = self.dh(self.b, "profile", "set", "domain.default=b.com")
        self.assertEqual(out["scope"], "machine")                                     # B: as before 2.3
        self.assertNotIn("ask_once", out)
        code, out = self.dh(self.a, "profile", "set", "email.provider=resend")
        self.assertEqual(out["scope"], "project")                                     # A: its own
        code, out = self.dh(self.b, "profile", "set", "coolify.url=https://c.example.com", "--here")
        self.assertEqual(out["scope"], "project")                                     # --here still overrides once
        self.assertIn("`~/.deckhand/` (shared by every project)", (self.b / ".deckhand" / "RESUME.md").read_text(encoding="utf-8"))

    def test_a_folder_outside_the_project_carries_the_projects_own_layer_along(self):
        self.project(self.a)
        profile.use_project(self.a)
        profile.set_fields(["domain.default=a.com"])
        profile.vault_set("RESEND_API_KEY", "coolify-a-444")
        (self.a / ".deckhand" / "profile.md").write_text("- Registrar: Namecheap\n", encoding="utf-8")
        store = self.tmp / "secure" / "shop-a"
        code, out = self.dh(self.a, "profile", "where", "--set", str(store))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["moved"], {"profile": ["domain.default"], "vault": ["RESEND_API_KEY"], "notes_md": True})
        self.assertEqual(Path(out["writes"]["vault"]), store / "vault.env")
        self.assertFalse((self.a / ".deckhand" / "vault.env").exists(), "one copy of a secret, not two")
        self.assertFalse((self.a / ".deckhand" / "profile.json").exists())
        self.assertFalse((self.a / ".deckhand" / "profile.md").exists())
        if os.name != "nt":
            self.assertEqual(oct(os.stat(store / "vault.env").st_mode)[-3:], "600")
        profile.use_project(self.a)
        self.assertEqual(profile.secret("RESEND_API_KEY"), "coolify-a-444")
        self.assertEqual(profile.load()["domain"]["default"], "a.com")
        code, out = self.dh(self.a, "profile", "set", "email.provider=brevo")
        self.assertEqual(Path(out["path"]), store / "profile.json")
        code, out = self.dh(self.a, "profile", "show")
        self.assertIn("Registrar: Namecheap", out["notes_md"]["facts"])
        # back home: everything returns to .deckhand/
        code, out = self.dh(self.a, "profile", "where", "--set", "here")
        self.assertEqual(sorted(out["moved"]), ["notes_md", "profile", "vault"])
        profile.use_project(self.a)
        self.assertEqual(profile.secret("RESEND_API_KEY"), "coolify-a-444")
        self.assertEqual(profile.load()["email"]["provider"], "brevo")

    def test_a_client_project_keeps_its_scope_in_a_folder_and_can_never_share_the_machine(self):
        self.project(self.a, "--for", "client")
        profile.use_project(self.a)
        profile.set_fields(["owner.name=Client A"])                                 # a client's layer holds everything
        self.assertFalse(self.machine().exists())
        code, out = self.dh(self.a, "profile", "where", "--set", "machine")
        self.assertEqual((code, out["code"]), (1, "CLIENT_PROJECT"))
        store = self.tmp / "clients" / "a"
        self.assertEqual(self.dh(self.a, "profile", "where", "--set", str(store))[0], 0)
        self.assertEqual(json.loads((self.a / ".deckhand" / "profile.json").read_text(encoding="utf-8"))["scope"], "client")
        profile.use_project(self.a)
        self.assertEqual(profile.scope(), "client")
        self.assertEqual(profile.load()["owner"]["name"], "Client A")

    def test_refusals_change_nothing(self):
        self.project(self.a)
        code, out = self.dh(self.a, "profile", "where", "--set", str(self.a / "secrets"))
        self.assertEqual(out["code"], "IN_PROJECT")                                  # could end up committed
        code, out = self.dh(self.a, "profile", "where", "--set", os.environ["DECKHAND_HOME"])
        self.assertEqual(out["code"], "IS_MACHINE")
        (self.tmp / "afile").write_text("x", encoding="utf-8")
        code, out = self.dh(self.a, "profile", "where", "--set", str(self.tmp / "afile"))
        self.assertEqual(out["code"], "NOT_A_FOLDER")
        self.assertFalse((self.a / ".deckhand" / "layout.json").exists())
        plain = self.tmp / "plain"
        plain.mkdir()
        code, out = self.dh(plain, "profile", "where", "--set", "here")
        self.assertEqual(out["code"], "NO_PROJECT")
        code, out = self.dh(plain, "profile", "set", "domain.default=x.com")        # outside a project: the machine, as before
        self.assertEqual(out["scope"], "machine")

    def test_a_value_on_both_sides_stops_the_move_and_names_it_without_its_value(self):
        self.project(self.a)
        profile.use_project(self.a)
        profile.vault_set("RESEND_API_KEY", "project-side-555")
        store = self.tmp / "store"
        store.mkdir()
        (store / "vault.env").write_text("RESEND_API_KEY='other-side-666'\n", encoding="utf-8")
        before = (self.a / ".deckhand" / "vault.env").read_bytes(), (self.a / ".deckhand" / "layout.json").read_bytes()
        code, out = self.dh(self.a, "profile", "where", "--set", str(store))
        self.assertEqual((out["code"], out["names"]), ("CONFLICT", ["RESEND_API_KEY"]))
        self.assertNotIn("666", json.dumps(out))
        self.assertNotIn("555", json.dumps(out))
        self.assertEqual(((self.a / ".deckhand" / "vault.env").read_bytes(), (self.a / ".deckhand" / "layout.json").read_bytes()), before)


class PlanToApp(Base):
    def test_the_app_folder_gets_the_planning_folders_choice_and_its_own_settings(self):
        self.project(self.a)
        profile.use_project(self.a)
        profile.set_fields(["domain.default=a.com"])
        profile.vault_set("RESEND_API_KEY", "planned-key-121")
        app = self.tmp / "shop-a-app"
        app.mkdir()
        (app / "package.json").write_text('{"name": "shop-a-app"}', encoding="utf-8")
        code, out = self.dh(self.a, "adopt", str(app))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["carried"], {"profile": ["domain.default"], "vault": ["RESEND_API_KEY"], "location": "here"})
        profile.use_project(app)
        self.assertEqual(profile.secret("RESEND_API_KEY"), "planned-key-121")         # the build finds what define stored
        self.assertEqual(profile.load()["domain"]["default"], "a.com")
        self.assertEqual(profile.binding()["location"], "here")
        if os.name != "nt":
            self.assertEqual(oct(os.stat(app / ".deckhand" / "vault.env").st_mode)[-3:], "600")

    def test_a_folder_choice_is_shared_by_the_app_not_copied(self):
        self.project(self.a)
        store = self.tmp / "store"
        self.dh(self.a, "profile", "where", "--set", str(store))
        profile.use_project(self.a)
        profile.vault_set("RESEND_API_KEY", "folder-key-131")
        app = self.tmp / "app"
        app.mkdir()
        (app / "package.json").write_text('{"name": "app"}', encoding="utf-8")
        code, out = self.dh(self.a, "adopt", str(app))
        self.assertEqual(out["carried"], {"shared_folder": str(store.resolve())})
        self.assertFalse((app / ".deckhand" / "vault.env").exists())
        profile.use_project(app)
        self.assertTrue(profile.binding()["ok"])
        self.assertEqual(profile.secret("RESEND_API_KEY"), "folder-key-131")
        code, out = self.dh(app, "profile", "where", "here")
        self.assertEqual(out["code"], "USAGE")                                        # one form: --set


class OwnersInfrastructure(Base):
    """The simulation: the server, DNS and GitHub keys landed in the first project, so every new project asked again."""

    def test_the_owners_server_dns_and_github_stay_on_the_machine_a_business_key_stays_in_its_project(self):
        self.project(self.a)
        self.project(self.b)
        profile.use_project(self.a)
        for name in ("COOLIFY_TOKEN", "CLOUDFLARE_API_TOKEN", "GITHUB_TOKEN"):
            self.assertEqual(profile.vault_set(name, f"{name.lower()}-owner")["scope"], "machine", name)
        self.assertEqual(profile.set_fields(["coolify.url=https://c.example", "vps.ip=203.0.113.9", "github.user=hakim"])["scope"], "machine")
        self.assertEqual(profile.vault_set("STRIPE_SECRET_KEY", "sk-shop-a")["scope"], "project")
        profile.use_project(self.b)
        saved = os.environ.pop("GITHUB_TOKEN", None)
        try:
            self.assertEqual(profile.secret("COOLIFY_TOKEN"), "coolify_token-owner", "project B never asks the owner's server again")
            self.assertEqual(profile.secret("GITHUB_TOKEN"), "github_token-owner")
        finally:
            if saved is not None:
                os.environ["GITHUB_TOKEN"] = saved
        self.assertIsNone(profile.secret("STRIPE_SECRET_KEY"), "project A's payments key is not project B's")

    def test_a_client_keeps_its_own_server_and_a_broken_client_layer_never_falls_back_to_the_owners_keys(self):
        profile.vault_set("COOLIFY_TOKEN", "owner-server", where="machine")
        self.project(self.a, "--for", "client")
        store = self.tmp / "client-store"
        self.dh(self.a, "profile", "where", "--set", str(store))
        profile.use_project(self.a)
        self.assertEqual(profile.vault_set("COOLIFY_TOKEN", "client-server")["scope"], "project")
        self.assertEqual(profile.secret("COOLIFY_TOKEN"), "client-server")
        shutil.rmtree(store)
        self.assertIsNone(profile.secret("COOLIFY_TOKEN"), "never the owner's server for a client's site")

    def test_dh_tryon_passes_the_project_after_the_action(self):
        from dhlib.cli import tryon_argv
        self.assertEqual(tryon_argv(["flags", "report", "--ids", "F1"], "/p"), ["flags", "report", "--ids", "F1", "--project", "/p"])
        self.assertEqual(tryon_argv(["--", "registry", "check", "--id", "all"], "/p")[:3], ["registry", "check", "--id"])
        self.assertEqual(tryon_argv(["serve", "--project", "/q"], "/p"), ["serve", "--project", "/q"])


class Broken(Base):
    def test_a_missing_folder_refuses_writes_reports_everywhere_and_one_command_fixes_it(self):
        self.project(self.a)
        store = self.tmp / "usb" / "shop-a"
        self.dh(self.a, "profile", "where", "--set", str(store))
        profile.use_project(self.a)
        profile.vault_set("RESEND_API_KEY", "on-the-usb-777")
        shutil.move(str(self.tmp / "usb"), str(self.tmp / "usb-unplugged"))           # the drive is not mounted
        code, out = self.dh(self.a, "profile", "set", "domain.default=a.com")
        self.assertEqual((code, out["code"]), (1, "BINDING_BROKEN"))
        self.assertIn("not there", out["message"])
        self.assertFalse(self.machine().exists(), "nothing written elsewhere instead")
        self.assertEqual(self.dh(self.a, "profile", "set", "github.user=hakim", "--machine")[0], 0)   # the machine still works
        code, out = self.dh(self.a, "profile", "where")
        self.assertFalse(out["ok"])
        self.assertIn("problem", out)
        self.assertIn("**BROKEN**", (self.a / ".deckhand" / "RESUME.md").read_text(encoding="utf-8"))
        for cmd in (("next",), ("resume",), ("status",), ("profile", "show"), ("vault", "list"), ("profile", "doctor", "--offline")):
            self.assertEqual(self.dh(self.a, *cmd)[0], 0, cmd)                       # the pipeline keeps running
        shutil.move(str(self.tmp / "usb-unplugged"), str(self.tmp / "usb"))           # plugged back in: works again
        profile.use_project(self.a)
        self.assertEqual(profile.secret("RESEND_API_KEY"), "on-the-usb-777")

    def test_a_copied_project_never_shares_the_originals_folder_and_a_corrupt_layout_is_reported(self):
        self.project(self.a)
        store = self.tmp / "store-a"
        self.dh(self.a, "profile", "where", "--set", str(store))
        shutil.copytree(self.a, self.b)
        code, out = self.dh(self.b, "profile", "set", "domain.default=b.com")
        self.assertEqual(out["code"], "BINDING_BROKEN")
        self.assertIn("a copy never shares", out["message"])
        self.assertEqual(self.dh(self.b, "profile", "where", "--set", "here")[0], 0)  # the owner decides; then it works
        self.assertEqual(self.dh(self.b, "profile", "set", "domain.default=b.com")[1]["scope"], "project")
        (self.a / ".deckhand" / "layout.json").write_text("{not json", encoding="utf-8")
        code, out = self.dh(self.a, "vault", "list")
        self.assertFalse(out["where"]["ok"])
        profile.use_project(self.a)
        with self.assertRaises(DhError) as e:
            profile.vault_set("X_KEY", "value-888")
        self.assertEqual(e.exception.code, "BINDING_BROKEN")


class Guarantees(Base):
    def test_the_layout_and_the_projects_notes_are_never_committed(self):
        self.project(self.a)
        self.dh(self.a, "profile", "set", "domain.default=a.com")
        subprocess.run(["git", "init", "-q"], cwd=self.a, check=True)
        for f in (".deckhand/layout.json", ".deckhand/profile.md", ".deckhand/profile.json", ".deckhand/vault.env"):
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", f], cwd=self.a).returncode, 0, f)

    def test_the_ops_clients_and_handoff_follow_the_choice_and_handoff_never_prints_a_local_path(self):
        self.project(self.a)
        store = self.tmp / "secret-store"
        self.dh(self.a, "profile", "where", "--set", str(store))
        profile.use_project(self.a)
        profile.vault_set("COOLIFY_TOKEN", "coolify-folder-999", where="here")      # the owner's server, kept with this project
        profile.vault_set("HOSTINGER_API_TOKEN", "hostinger-folder-000", where="here")
        profile.set_fields(["coolify.url=http://127.0.0.1:8000"], where="here")
        import coolify_api as CA
        import hostinger_api as HA
        importlib.reload(CA)
        self.assertEqual(CA.resolve(home=self.tmp / "none"), ("http://127.0.0.1:8000", "coolify-folder-999"))
        self.assertEqual(HA._vault_token(), "hostinger-folder-000")
        code, out = self.dh(self.a, "handoff")
        text = (self.a / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("in a folder outside the project", text)
        self.assertNotIn(str(store), text)
        self.assertNotIn("coolify-folder-999", text)


if __name__ == "__main__":
    unittest.main()
