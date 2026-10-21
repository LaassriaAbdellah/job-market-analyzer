-- Exécuter après email_setup.sql
CREATE TABLE IF NOT EXISTS email_schedules (
    profile_id BIGINT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    recipient_email TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    send_hour SMALLINT NOT NULL DEFAULT 9 CHECK (send_hour BETWEEN 0 AND 23),
    send_minute SMALLINT NOT NULL DEFAULT 0 CHECK (send_minute BETWEEN 0 AND 59),
    timezone TEXT NOT NULL DEFAULT 'Africa/Casablanca',
    max_jobs INTEGER NOT NULL DEFAULT 5 CHECK (max_jobs BETWEEN 1 AND 20),
    min_score DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (min_score BETWEEN 0 AND 100),
    last_attempt_date DATE,
    last_status TEXT,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
