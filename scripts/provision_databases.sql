-- One-time local provisioning for the HMS (run as a PostgreSQL superuser).
--
-- Creates a least-privilege application role and two SEPARATE databases:
--   hms_dev   primary development database   (DATABASE_URL)
--   hms_test  isolated test database          (TEST_DATABASE_URL)
--
-- The password is supplied at run time and is never stored in this file:
--
--   psql -U postgres -h localhost -v app_password="<choose one>" -f scripts/provision_databases.sql
--
-- Safe to re-run: existing role/databases are left in place (the password is reset).
-- Tables are NOT created here — schema is managed exclusively by Alembic.

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE hms_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hms_app')
\gexec

SELECT format('ALTER ROLE hms_app LOGIN PASSWORD %L', :'app_password')
\gexec

SELECT 'CREATE DATABASE hms_dev OWNER hms_app ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'hms_dev')
\gexec

SELECT 'CREATE DATABASE hms_test OWNER hms_app ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'hms_test')
\gexec
