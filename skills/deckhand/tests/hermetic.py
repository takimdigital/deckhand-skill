"""A test must never read the machine it runs on. Importing this module removes the secret-shaped variables a developer's
shell or a CI job may carry (Coolify, Cloudflare, VPS ssh), so the suite gives the same answer everywhere. A test that needs
one sets it itself, after the import."""
import os

PREFIXES = ("COOLIFY_", "VPS_", "CF_")
NAMES = ("FREELLMAPI_KEY", "RESEND_API_KEY", "MAILGUN_API_KEY", "BREVO_API_KEY")

for _k in list(os.environ):
    if _k.startswith(PREFIXES) or _k in NAMES:
        os.environ.pop(_k, None)
