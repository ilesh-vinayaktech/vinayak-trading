-- Portal authentication core: users, sessions, login attempts, recovery codes, one-time tokens, append-only audit.
-- Secrets (2FA seed) are stored encrypted (see algo.portal.crypto); passwords only as Argon2id hashes; session and
-- token values only as SHA-256 hashes.
CREATE TABLE portal_user (
  user_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email                TEXT NOT NULL,
  display_name         TEXT NOT NULL,
  role                 TEXT NOT NULL CHECK (role IN ('ADMIN', 'OPERATOR', 'TRADER', 'VIEWER')),
  status               TEXT NOT NULL CHECK (status IN ('INVITED', 'ACTIVE', 'SUSPENDED', 'DISABLED')),
  password_hash        TEXT,
  password_changed_at  TIMESTAMPTZ,
  must_change_password BOOLEAN NOT NULL DEFAULT false,
  totp_secret_enc      TEXT,
  totp_enabled         BOOLEAN NOT NULL DEFAULT false,
  totp_last_step       BIGINT,
  last_login_at        TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL,
  created_by           UUID REFERENCES portal_user(user_id)
);
CREATE UNIQUE INDEX portal_user_email_key ON portal_user (lower(email));

CREATE TABLE portal_session (
  session_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash      TEXT NOT NULL UNIQUE,
  user_id         UUID NOT NULL REFERENCES portal_user(user_id),
  csrf_token_hash TEXT NOT NULL,
  mfa_verified    BOOLEAN NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL,
  last_seen_at    TIMESTAMPTZ NOT NULL,
  expires_at      TIMESTAMPTZ NOT NULL,
  ip              TEXT,
  user_agent      TEXT,
  revoked_at      TIMESTAMPTZ
);
CREATE INDEX portal_session_user ON portal_session (user_id) WHERE revoked_at IS NULL;

CREATE TABLE portal_login_attempt (
  attempt_id BIGSERIAL PRIMARY KEY,
  email_hash TEXT NOT NULL,
  ip         TEXT,
  at         TIMESTAMPTZ NOT NULL,
  outcome    TEXT NOT NULL CHECK (outcome IN ('SUCCESS', 'FAILURE'))
);
CREATE INDEX portal_login_attempt_email ON portal_login_attempt (email_hash, at);
CREATE INDEX portal_login_attempt_ip ON portal_login_attempt (ip, at);

CREATE TABLE portal_recovery_code (
  user_id   UUID NOT NULL REFERENCES portal_user(user_id),
  code_hash TEXT NOT NULL,
  used_at   TIMESTAMPTZ,
  PRIMARY KEY (user_id, code_hash)
);

CREATE TABLE portal_token (
  token_hash TEXT PRIMARY KEY,
  user_id    UUID NOT NULL REFERENCES portal_user(user_id),
  purpose    TEXT NOT NULL CHECK (purpose IN ('INVITE', 'RESET')),
  created_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at    TIMESTAMPTZ
);

CREATE TABLE portal_audit (
  audit_id      BIGSERIAL PRIMARY KEY,
  at            TIMESTAMPTZ NOT NULL,
  actor_user_id UUID,
  actor_label   TEXT NOT NULL,
  action        TEXT NOT NULL,
  target_type   TEXT,
  target_id     TEXT,
  detail        JSONB NOT NULL DEFAULT '{}'::jsonb,
  ip            TEXT,
  user_agent    TEXT,
  request_id    TEXT
);
CREATE INDEX portal_audit_actor ON portal_audit (actor_user_id, at DESC);
CREATE INDEX portal_audit_target ON portal_audit (target_type, target_id, at DESC);

-- the audit trail is append-only: rows can never be changed or removed through SQL
CREATE FUNCTION portal_audit_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'portal_audit is append-only';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER portal_audit_no_change BEFORE UPDATE OR DELETE ON portal_audit
  FOR EACH ROW EXECUTE FUNCTION portal_audit_immutable();
CREATE TRIGGER portal_audit_no_wipe BEFORE TRUNCATE ON portal_audit
  FOR EACH STATEMENT EXECUTE FUNCTION portal_audit_immutable();
