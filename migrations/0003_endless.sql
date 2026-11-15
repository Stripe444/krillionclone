-- Endless mode: a large prepared question bank, and the prompts each practice run drew.
CREATE TABLE IF NOT EXISTS bank (
  id TEXT PRIMARY KEY,
  family TEXT NOT NULL,
  grp TEXT NOT NULL,
  content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bank_groups ON bank(grp);
ALTER TABLE runs ADD COLUMN prompt_ids TEXT;
