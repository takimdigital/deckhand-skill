-- mail-router schema — run once in the app's Postgres (or port to Drizzle migrations).

CREATE TABLE IF NOT EXISTS email_quota (
  provider text NOT NULL,
  utc_day  date NOT NULL,
  sent     int  NOT NULL DEFAULT 0,
  PRIMARY KEY (provider, utc_day)
);

CREATE TABLE IF NOT EXISTS email_attempt (
  id          bigserial PRIMARY KEY,
  message_key text NOT NULL,
  provider    text NOT NULL,
  outcome     text NOT NULL,            -- sent | fail | permanent
  error       text NOT NULL DEFAULT '',
  at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (message_key, provider)
);

CREATE TABLE IF NOT EXISTS email_alert_state (
  provider text NOT NULL,
  reason   text NOT NULL,
  at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, reason)
);
