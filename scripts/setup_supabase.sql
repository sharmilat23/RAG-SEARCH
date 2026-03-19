-- ═══════════════════════════════════════════════════════════
-- Supabase SQL: Chat Memory Table
-- Run this in your Supabase SQL Editor (Dashboard → SQL Editor)
-- This creates the table used by chat_memory.py
-- ═══════════════════════════════════════════════════════════

-- Chat memory table (replicates n8n Postgres Chat Memory node)
CREATE TABLE IF NOT EXISTS chat_memory (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast session lookups
CREATE INDEX IF NOT EXISTS idx_chat_memory_session
    ON chat_memory (session_id, created_at);

-- ═══════════════════════════════════════════════════════════
-- Supabase SQL: match_documents RPC function
-- This is the vector similarity search function used by the 
-- RAG pipeline (replicates n8n Supabase Vector Store retrieval)
-- ═══════════════════════════════════════════════════════════

-- NOTE: This function assumes your "documents" table has:
--   - id (bigint)
--   - content (text)
--   - metadata (jsonb)
--   - embedding (vector)
--
-- If your table structure differs, adjust accordingly.
-- The pgvector extension should already be enabled if you
-- used n8n's Supabase Vector Store for ingestion.

CREATE OR REPLACE FUNCTION match_documents(
    query_embedding vector(768),
    match_count int DEFAULT 5
)
RETURNS TABLE (
    id bigint,
    content text,
    metadata jsonb,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.content,
        d.metadata,
        1 - (d.embedding <=> query_embedding) AS similarity
    FROM documents d
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
