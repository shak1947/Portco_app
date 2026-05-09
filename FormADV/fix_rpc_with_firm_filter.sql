-- RPC with proper firm filtering support
DROP FUNCTION IF EXISTS match_documents(vector, int, float) CASCADE;

CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_count int DEFAULT 10,
  match_threshold float DEFAULT 0.0,
  firm_name_filter text DEFAULT NULL
)
RETURNS TABLE (
  id text,
  firm_name text,
  source_file text,
  page_number int,
  text text,
  similarity float
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    fae.id,
    fae.firm_name,
    fae.source_file,
    fae.page_number,
    fae.text,
    (1.0 - (fae.embedding <=> query_embedding))::float AS similarity
  FROM form_adv_embeddings fae
  WHERE (firm_name_filter IS NULL OR fae.firm_name = firm_name_filter)
  ORDER BY fae.embedding <=> query_embedding
  LIMIT match_count;

  RETURN;
END;
$$ LANGUAGE plpgsql STABLE;

GRANT EXECUTE ON FUNCTION match_documents(vector, int, float, text) TO authenticated, anon;
