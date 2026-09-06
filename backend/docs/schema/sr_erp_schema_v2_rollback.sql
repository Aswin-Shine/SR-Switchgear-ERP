-- =============================================================================
-- SR Switchgear ERP — Schema v2
-- Migration: 001_init_modules_1_and_2  (DOWN / rollback)
--
-- WARNING: destroys all data in these schemas. Take a dump first:
--   pg_dump -Fc -n core -n hr -n auth -n sales -n pipeline srerp > pre_rollback.dump
-- =============================================================================

BEGIN;

DROP SCHEMA IF EXISTS sales    CASCADE;
DROP SCHEMA IF EXISTS pipeline CASCADE;
DROP SCHEMA IF EXISTS hr       CASCADE;
DROP SCHEMA IF EXISTS auth     CASCADE;
DROP SCHEMA IF EXISTS core     CASCADE;

-- citext is left installed; other objects may depend on it.
-- To remove it explicitly:  DROP EXTENSION IF EXISTS citext;

COMMIT;
