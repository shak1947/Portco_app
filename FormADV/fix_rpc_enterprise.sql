-- Drop existing function to rebuild it properly
DROP FUNCTION IF EXISTS match_documents(vector, int, float) CASCADE;

-- Create improved RPC with better error handling and explicit type casting
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_count int DEFAULT 10,
  match_threshold float DEFAULT 0.2
)
RETURNS TABLE (
  id text,
  firm_name text,
  source_file text,
  page_number int,
  text text,
  similarity float
) AS $$
DECLARE
  v_threshold float;
BEGIN
  -- Ensure threshold is valid (0 to 1)
  v_threshold := CASE
    WHEN match_threshold < 0 THEN 0
    WHEN match_threshold > 1 THEN 1
    ELSE match_threshold
  END;

  RETURN QUERY
  SELECT
    fae.id,
    fae.firm_name,
    fae.source_file,
    fae.page_number,
    fae.text,
    (1.0 - (fae.embedding <=> query_embedding))::float AS similarity
  FROM form_adv_embeddings fae
  ORDER BY fae.embedding <=> query_embedding
  LIMIT match_count;

  RETURN;
END;
$$ LANGUAGE plpgsql STABLE;

-- Create index for vector search if not exists
CREATE INDEX IF NOT EXISTS form_adv_embeddings_embedding_idx
ON form_adv_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Grant execute permission
GRANT EXECUTE ON FUNCTION match_documents(vector, int, float) TO authenticated, anon;
