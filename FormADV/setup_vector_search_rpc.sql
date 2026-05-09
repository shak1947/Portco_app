-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create RPC function for vector similarity search
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector,
  match_count int DEFAULT 10,
  match_threshold float DEFAULT 0.0
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
    form_adv_embeddings.id,
    form_adv_embeddings.firm_name,
    form_adv_embeddings.source_file,
    form_adv_embeddings.page_number,
    form_adv_embeddings.text,
    (1 - (form_adv_embeddings.embedding <=> query_embedding))::float AS similarity
  FROM form_adv_embeddings
  WHERE (1 - (form_adv_embeddings.embedding <=> query_embedding)) > match_threshold
  ORDER BY form_adv_embeddings.embedding <=> query_embedding
  LIMIT match_count;
END;
$$ LANGUAGE plpgsql;
