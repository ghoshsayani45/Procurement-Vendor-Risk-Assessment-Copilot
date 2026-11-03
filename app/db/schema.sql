-- Procurement & Vendor Risk Copilot: initial schema (Day 0 / Week 2). Loaded by docker compose on first start.
-- Tables follow the solution document, plus conversation_turns for multi-turn state.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS vendors (
    id              TEXT PRIMARY KEY,           -- V001..V035
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ACTIVE','PROSPECT','DEBARRED','EXITED')),
    owner           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,           -- corpus doc_id
    vendor_id       TEXT REFERENCES vendors(id),
    source_id       TEXT NOT NULL,              -- source register id (POL-001, SYN-..., CON-001 ...)
    slice           TEXT NOT NULL,
    type            TEXT NOT NULL,
    title           TEXT NOT NULL,
    version         TEXT,
    effective_date  DATE,
    access_class    TEXT NOT NULL DEFAULT 'internal' CHECK (access_class IN ('public','internal','restricted')),
    licence         TEXT,
    sha1            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq             INT  NOT NULL,
    text            TEXT NOT NULL,
    embedding       VECTOR,                     -- dimension fixed once the embeddings endpoint is measured (Day 0)
    keywords        TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_fts ON chunks USING GIN (keywords);

CREATE TABLE IF NOT EXISTS financial_metrics (
    vendor_id       TEXT NOT NULL REFERENCES vendors(id),
    period          TEXT NOT NULL,
    metric          TEXT NOT NULL,
    value           NUMERIC NOT NULL,
    source          TEXT NOT NULL,
    PRIMARY KEY (vendor_id, period, metric)
);

CREATE TABLE IF NOT EXISTS reviews (
    id              UUID PRIMARY KEY,
    vendor_id       TEXT NOT NULL REFERENCES vendors(id),
    review_type     TEXT NOT NULL CHECK (review_type IN ('NEW_VENDOR','RENEWAL')),
    status          TEXT NOT NULL DEFAULT 'OPEN',
    as_of           DATE NOT NULL,
    score_json      JSONB,
    report_json     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    id              BIGSERIAL PRIMARY KEY,
    review_id       UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
    content         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only: who asked what, which tools ran, which sources, which human decisions.
CREATE TABLE IF NOT EXISTS audit_events (
    id              BIGSERIAL PRIMARY KEY,
    review_id       UUID REFERENCES reviews(id),
    actor           TEXT NOT NULL,              -- user id, 'copilot', or tool name
    action          TEXT NOT NULL,              -- REQUEST | TOOL_CALL | REFUSAL | INJECTION_DETECTED | HUMAN_DECISION ...
    decision        TEXT,
    detail          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE OR REPLACE RULE audit_no_update AS ON UPDATE TO audit_events DO INSTEAD NOTHING;
CREATE OR REPLACE RULE audit_no_delete AS ON DELETE TO audit_events DO INSTEAD NOTHING;
