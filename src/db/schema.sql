-- Run once per database (requires pgvector in PostgreSQL image)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS user_settings (
    user_id BIGINT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'ingest' CHECK (mode IN ('ingest', 'chat')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- embedding dimension is set at migration time; must match EMBEDDING_DIM / model output
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_chunks_user_id_idx ON knowledge_chunks (user_id);

-- HNSW for cosine similarity (replace vector(1536) in table if you change dim — recreate index)
CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw_idx
ON knowledge_chunks
USING hnsw (embedding vector_cosine_ops);
