-- D1 schema for the token-economy account server. Safe to run twice.

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  email_verified INTEGER NOT NULL DEFAULT 0,
  -- Every account is 'free' today; paid plans flip this column, nothing else.
  plan TEXT NOT NULL DEFAULT 'free',
  source TEXT NOT NULL DEFAULT 'cli',
  created_at INTEGER NOT NULL
);

-- API keys are stored as SHA-256 hashes only.
CREATE TABLE IF NOT EXISTS api_keys (
  key_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  last_used_at INTEGER
);
CREATE INDEX IF NOT EXISTS api_keys_user ON api_keys(user_id);

-- Device-code sign-in: the CLI holds device_code, the person types user_code in the browser.
CREATE TABLE IF NOT EXISTS device_codes (
  device_code_hash TEXT PRIMARY KEY,
  user_code TEXT NOT NULL UNIQUE,
  user_id INTEGER,
  emails_sent INTEGER NOT NULL DEFAULT 0,
  expires_at INTEGER NOT NULL
);

-- Short-lived tokens: 'confirm' (email link, POST to use), 'link' (one-time dashboard link), 'session' (dashboard cookie).
CREATE TABLE IF NOT EXISTS tokens (
  token_hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  user_id INTEGER,
  ref TEXT,
  -- confirm tokens carry the email; the account is created only when the link is confirmed.
  email TEXT,
  expires_at INTEGER NOT NULL
);

-- Hourly counters for sign-in starts, emails sent and web sign-ups.
CREATE TABLE IF NOT EXISTS rate_limits (
  key TEXT PRIMARY KEY,
  win INTEGER NOT NULL,
  count INTEGER NOT NULL
);

-- Daily summary counts uploaded by scripts/account.py. project is a salted hash made on the client.
CREATE TABLE IF NOT EXISTS usage (
  user_id INTEGER NOT NULL,
  device_id TEXT NOT NULL,
  day TEXT NOT NULL,
  project TEXT NOT NULL,
  sessions INTEGER NOT NULL DEFAULT 0,
  steps INTEGER NOT NULL DEFAULT 0,
  reread INTEGER NOT NULL DEFAULT 0,
  out_tokens INTEGER NOT NULL DEFAULT 0,
  tool_bytes INTEGER NOT NULL DEFAULT 0,
  blocks INTEGER NOT NULL DEFAULT 0,
  checks INTEGER NOT NULL DEFAULT 0,
  denials INTEGER NOT NULL DEFAULT 0,
  overrides INTEGER NOT NULL DEFAULT 0,
  version TEXT,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, device_id, day, project)
);
