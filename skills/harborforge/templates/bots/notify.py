"""notify.py — one message, any channel (stdlib). Channel from env: TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID,
DISCORD_WEBHOOK_URL, NOTIFY_WEBHOOK_URL (JSON {"text"}), or SMTP_URL (smtp[s]://user:pass@host:port/to@addr).
Deduplication: send() only when the message differs from the last one sent with the same key."""
from __future__ import annotations

import hashlib, json, os, smtplib, urllib.parse, urllib.request
from email.message import EmailMessage
from pathlib import Path

STATE = Path(os.environ.get("BOT_STATE_DIR", Path.home() / ".deckhand-bots"))


def _post(url: str, payload: dict) -> None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "deckhand-bot"})
    urllib.request.urlopen(req, timeout=20).read()


def deliver(text: str, title: str = "deckhand") -> list:
    if os.environ.get("DECKHAND_NOTIFY") == "stdout":      # a Hermes no-agent cron job: stdout IS the delivered message
        print(f"{title}\n{text}")
        return ["stdout"]
    sent = []
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        _post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
              {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": f"{title}\n{text}", "disable_web_page_preview": True})
        sent.append("telegram")
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        _post(os.environ["DISCORD_WEBHOOK_URL"], {"content": f"**{title}**\n{text}"[:1990]})
        sent.append("discord")
    if os.environ.get("NOTIFY_WEBHOOK_URL"):
        _post(os.environ["NOTIFY_WEBHOOK_URL"], {"title": title, "text": text})
        sent.append("webhook")
    if os.environ.get("SMTP_URL"):
        u = urllib.parse.urlparse(os.environ["SMTP_URL"])
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = title, u.username or "bot@localhost", u.path.lstrip("/")
        msg.set_content(text)
        cls = smtplib.SMTP_SSL if u.scheme == "smtps" else smtplib.SMTP
        with cls(u.hostname, u.port or (465 if u.scheme == "smtps" else 587), timeout=30) as s:
            if u.scheme != "smtps":
                s.starttls()
            if u.username:
                s.login(urllib.parse.unquote(u.username), urllib.parse.unquote(u.password or ""))
            s.send_message(msg)
        sent.append("email")
    return sent


def send(key: str, text: str, title: str = "deckhand") -> list:
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / f"{key}.last"
    h = hashlib.sha256(text.encode()).hexdigest()
    if f.exists() and f.read_text() == h:
        return []
    out = deliver(text, title)
    f.write_text(h)
    return out
