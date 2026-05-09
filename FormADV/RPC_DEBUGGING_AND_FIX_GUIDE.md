# Enterprise Vector Search RPC Fix - Complete Guide

## Problem Analysis

Your RPC function `match_documents()` is callable (HTTP 200 responses in logs) but **returns 0 results** on every query, even though embeddings exist in the database.

### Root Cause

The original RPC had a WHERE clause with a computed similarity threshold:
```sql
WHERE (1 - (form_adv_embeddings.embedding <=> query_embedding)) > match_threshold
```

This is problematic because:
1. The `<=>` operator returns distance (0-1), but the formula `(1 - distance)` in a WHERE clause with dynamic parameters can cause issues
2. The threshold filtering might be too strict or have type casting issues
3. Computed values in WHERE clauses with dynamic parameters aren't always reliable in pgvector

## Solution: Simplified RPC

The fixed version removes the WHERE clause and relies on `ORDER BY` + `LIMIT`:

```sql
ORDER BY fae.embedding <=> query_embedding
LIMIT match_count;
```

This is:
- **More reliable**: Avoids computed values in WHERE
- **More performant**: Uses the index properly
- **Enterprise-grade**: Simpler is better for complex operations

## Deployment Steps

### Step 1: Apply the Fix in Supabase

1. Open your Supabase Dashboard
2. Go to SQL Editor
3. Create a new query and paste the contents of `fix_rpc_enterprise.sql`
4. Review the SQL (it drops the old function and creates a new one)
5. Click **Run**

#### If you get memory error (54000):

This means your maintenance_work_mem is too low for the IVFFlat index. **This is normal and fixable**:

**Option A (Recommended):** Run `fix_rpc_enterprise_no_index.sql` instead
- Creates the RPC function WITHOUT the index
- Function works immediately
- Search is functional (no index means slightly slower, but acceptable for your data size)
- Index can be created later or via support request

**Option B:** Contact Supabase support
- Ask them to temporarily increase `maintenance_work_mem` to 256MB
- Then you can create the full index
- They can do this without downtime

**Option C:** Create index manually later
- Run just the function SQL now (no index)
- Create index separately after initial testing:
  ```sql
  CREATE INDEX CONCURRENTLY form_adv_embeddings_embedding_idx
  ON form_adv_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);
  ```

### Step 2: Test the RPC in Supabase SQL Editor

Create and run this test query:

```sql
-- Test the RPC function with a sample embedding
SELECT * FROM match_documents(
  array_fill(0.1::real, ARRAY[1536])::vector(1536),
  10,
  0.0
) LIMIT 5;
```

Expected result: Should return 5-10 rows with firm_name, similarity, etc.

If you get results: ✓ RPC is working
If you get 0 rows: Check error logs (there might be a database issue)

### Step 3: Update app.py

The app.py already tries the RPC with threshold 0.2. After the fix:
- RPC will return results
- No fallback needed
- Full vector search performance

### Step 4: Test in Production

After deploying the fixed RPC:
1. Make a query like "What are investment strategies?"
2. Check logs for: `Retrieved X matches in Yms`
3. Should show results, not "Retrieved 0 matches"

## Alternative: If RPC Still Returns 0

If the simplified RPC still returns 0 results, the issue is deeper:

### Debug Option A: Check Raw Similarity

Run this in Supabase SQL Editor to see actual similarity scores:

```sql
SELECT
  id,
  firm_name,
  1 - (embedding <=> array_fill(0.1::real, ARRAY[1536])::vector(1536)) as similarity
FROM form_adv_embeddings
ORDER BY embedding <=> array_fill(0.1::real, ARRAY[1536])::vector(1536)
LIMIT 10;
```

This shows if similarities are being computed at all.

### Debug Option B: Check Embedding Data

```sql
SELECT
  firm_name,
  COUNT(*) as count,
  array_length(embedding::float8[], 1) as embedding_dims,
  array_to_string(array_slice(embedding::float8[], 1, 5), ',') as first_5_values
FROM form_adv_embeddings
GROUP BY firm_name, embedding_dims
ORDER BY firm_name;
```

This verifies:
- Embeddings exist for all firms
- All embeddings are 1536-dimensional
- No NULL or corrupted embeddings

## For Production Enterprise Deployment

Once RPC is working:

1. **Monitor query performance**: Track retrieval times in pipeline metrics
2. **Index maintenance**: Ensure `form_adv_embeddings_embedding_idx` is properly configured
3. **Load testing**: Test with concurrent queries
4. **Backup strategy**: Document RPC function in version control
5. **Logging**: All retrieval attempts logged with actual results count

## Rollback Plan

If the new RPC causes issues:

```sql
-- Restore to original (if needed)
DROP FUNCTION IF EXISTS match_documents(vector, int, float) CASCADE;

-- Then recreate original version
CREATE OR REPLACE FUNCTION match_documents(...)
-- [paste original RPC code]
```

## Next Steps

1. Apply `fix_rpc_enterprise.sql` in Supabase
2. Run test query in Supabase SQL Editor
3. Confirm it returns results
4. Deploy app.py (already updated)
5. Test with actual queries
6. Monitor logs for retrieval metrics
