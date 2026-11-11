-- Each user's own Kite Connect app credentials and daily access token. The key, secret and token are stored only encrypted
-- (algo.portal.crypto, bound to the owner and field); the hint is the last four characters of the API key, for display.
-- One connection may be marked as the SYSTEM data feed (an administrator's), used by the data loaders instead of a .env file.
CREATE TABLE portal_kite_connection (
  user_id            UUID PRIMARY KEY REFERENCES portal_user(user_id),
  api_key_enc        TEXT NOT NULL,
  api_secret_enc     TEXT NOT NULL,
  api_key_hint       TEXT NOT NULL,
  access_token_enc   TEXT,
  kite_user_id       TEXT,
  connected_at       TIMESTAMPTZ,
  token_expires_at   TIMESTAMPTZ,
  connect_state_hash TEXT,
  connect_state_expires TIMESTAMPTZ,
  is_system          BOOLEAN NOT NULL DEFAULT false,
  created_at         TIMESTAMPTZ NOT NULL,
  updated_at         TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX portal_kite_one_system ON portal_kite_connection ((true)) WHERE is_system;
