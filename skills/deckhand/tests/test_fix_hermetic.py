"""The suite must not depend on the secrets of the machine it runs on: a shell with COOLIFY_TOKEN loaded made a profile test
fail with the owner's real token in the message. Each case runs one secret-reading test with fake secrets in the environment."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
FAKE = {"COOLIFY_URL": "http://127.0.0.1:1", "COOLIFY_TOKEN": "FAKE-LEAK-123456", "CF_API_TOKEN": "FAKE-CF-123456",
        "VPS_SSH_HOST": "203.0.113.9", "VPS_SSH_KEY": "C:/nowhere/key", "VPS_KNOWN_HOSTS": "C:/nowhere/kh"}


def run_with_fake_secrets(pattern: str, name: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **FAKE, "PYTHONUTF8": "1"}
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-k", name],
                          cwd=SKILL, env=env, capture_output=True, text=True, encoding="utf-8", timeout=240)


class Hermetic(unittest.TestCase):
    def test_the_profile_secret_test_ignores_secrets_in_the_environment(self):
        r = run_with_fake_secrets("test_dh.py", "test_secrets_never_enter_the_profile")
        self.assertEqual(r.returncode, 0, r.stderr[-900:])
        self.assertIn("Ran 1 test", r.stderr)

    def test_every_test_module_that_reads_secrets_imports_hermetic(self):
        missing = []
        for p in sorted((SKILL / "tests").glob("test_*.py")):
            text = p.read_text(encoding="utf-8")
            if ("secret(" in text or "COOLIFY" in text or "CF_API_TOKEN" in text or "VPS_SSH" in text) and "import hermetic" not in text \
                    and p.name != Path(__file__).name:
                missing.append(p.name)
        self.assertEqual(missing, [], "add `import hermetic  # noqa: E402` after `import tmpclean` in these tests")


if __name__ == "__main__":
    unittest.main()
