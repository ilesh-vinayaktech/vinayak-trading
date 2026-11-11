-- CRM on top of the portal users: internal notes, tags, follow-up tasks, and support tickets with their conversation.
-- Notes, tags and tasks are staff-only (never shown to the person they are about). A ticket's messages may be marked
-- internal, which hides them from the requester.
CREATE TABLE portal_note (
  note_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seq        BIGSERIAL NOT NULL,                               -- a stable order when two rows share a timestamp
  user_id    UUID NOT NULL REFERENCES portal_user(user_id),
  author_id  UUID NOT NULL REFERENCES portal_user(user_id),
  body       TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 4000),
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX portal_note_user ON portal_note (user_id, created_at DESC);

CREATE TABLE portal_user_tag (
  user_id  UUID NOT NULL REFERENCES portal_user(user_id),
  tag      TEXT NOT NULL CHECK (tag ~ '^[a-z0-9][a-z0-9 _-]{0,29}$'),
  added_by UUID NOT NULL REFERENCES portal_user(user_id),
  added_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (user_id, tag)
);
CREATE INDEX portal_user_tag_tag ON portal_user_tag (tag);

CREATE TABLE portal_task (
  task_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID REFERENCES portal_user(user_id),          -- the person it is about, if any
  owner_id     UUID NOT NULL REFERENCES portal_user(user_id), -- who has to do it
  created_by   UUID NOT NULL REFERENCES portal_user(user_id),
  title        TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  detail       TEXT NOT NULL DEFAULT '' CHECK (length(detail) <= 4000),
  due_date     DATE,
  status       TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'DONE')),
  created_at   TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ
);
CREATE INDEX portal_task_owner ON portal_task (owner_id, status, due_date);
CREATE INDEX portal_task_user ON portal_task (user_id);

CREATE TABLE portal_ticket (
  ticket_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  number      BIGSERIAL NOT NULL UNIQUE,
  user_id     UUID NOT NULL REFERENCES portal_user(user_id),  -- the requester
  subject     TEXT NOT NULL CHECK (length(subject) BETWEEN 1 AND 200),
  status      TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'PENDING', 'RESOLVED', 'CLOSED')),
  priority    TEXT NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW', 'NORMAL', 'HIGH')),
  assignee_id UUID REFERENCES portal_user(user_id),
  created_at  TIMESTAMPTZ NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX portal_ticket_user ON portal_ticket (user_id, updated_at DESC);
CREATE INDEX portal_ticket_queue ON portal_ticket (status, updated_at DESC);

CREATE TABLE portal_ticket_message (
  message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seq        BIGSERIAL NOT NULL,                              -- a stable order when two rows share a timestamp
  ticket_id  UUID NOT NULL REFERENCES portal_ticket(ticket_id),
  author_id  UUID NOT NULL REFERENCES portal_user(user_id),
  body       TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
  internal   BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX portal_ticket_message_ticket ON portal_ticket_message (ticket_id, created_at);
