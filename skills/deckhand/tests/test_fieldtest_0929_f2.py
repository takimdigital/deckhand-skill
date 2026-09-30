"""F2: profile doctor under an isolated DECKHAND_HOME must not read ~/.vps-ops nor call Cloudflare with its token."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)
from dhlib import profile  # noqa: E402

NAMES = ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "COOLIFY_TOKEN", "VPS_OPS_HOME")


class F2(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.real = self.tmp / "realhome"
        (self.real / ".vps-ops" / "secrets").mkdir(parents=True)
        (self.real / ".vps-ops" / "secrets" / "cf.env.sh").write_text(
            "export CLOUDFLARE_API_TOKEN=abc\nexport COOLIFY_TOKEN=def\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()
        for n in NAMES:
            os.environ.pop(n, None)

    def tearDown(self):
        self.env.stop()
        tmpclean.rmtree(self.tmp)

    def test_F2_isolated_home_reads_no_v1_keyring_and_makes_no_call(self):
        with mock.patch("pathlib.Path.home", return_value=self.real), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network in an isolated home")):
            d = profile.doctor(online=True)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", d["secrets_present"])
        self.assertNotIn("COOLIFY_TOKEN", d["secrets_present"])
        self.assertFalse(d["capabilities"]["cloudflare"]["ok"])

    def test_F2_an_explicit_VPS_OPS_HOME_still_works(self):
        os.environ["VPS_OPS_HOME"] = str(self.real / ".vps-ops")
        self.assertEqual(profile.secret("COOLIFY_TOKEN"), "def")


if __name__ == "__main__":
    unittest.main()
