-- Extensions required by the memory platform.
-- pgvector      : vector embeddings + HNSW
-- pg_trgm       : fuzzy/typo-tolerant text (entity aliases)
-- btree_gist    : composite indexes with range overlap (bi-temporal edges)
-- ltree         : ontology hierarchy (materialized subtype path)
-- citext        : case-insensitive email
-- pgcrypto      : gen_random_uuid(), digest() helpers
--
-- Deferred to v1.1:
--   pg_jsonschema — CHECK-time JSON Schema validation on entity.props.
--   Until then, Pydantic validates at the API boundary. Add a custom
--   postgres image with supabase's pg_jsonschema build when ready.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Tunables (conservative defaults; tune per host).
ALTER SYSTEM SET shared_buffers = '512MB';
ALTER SYSTEM SET effective_cache_size = '1536MB';
ALTER SYSTEM SET maintenance_work_mem = '128MB';
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET wal_level = 'logical';
