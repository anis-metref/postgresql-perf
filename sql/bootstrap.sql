-- Structure minimale pour l'application
CREATE SCHEMA IF NOT EXISTS referentiels;

CREATE TABLE IF NOT EXISTS referentiels.adresse_postale (
    id BIGSERIAL PRIMARY KEY,
    numero INTEGER,
    nom_voie VARCHAR(255),
    nom_commune VARCHAR(100),
    code_post VARCHAR(5),
    lat DECIMAL(15,12),
    lon DECIMAL(15,12)
);

CREATE TABLE IF NOT EXISTS referentiels.etablissement (
    id BIGSERIAL PRIMARY KEY,
    siren VARCHAR(9),
    siret VARCHAR(14),
    numerovoieetablissement INTEGER,
    denominationunitelegale VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS referentiels.unite_legale (
    id BIGSERIAL PRIMARY KEY,
    siren VARCHAR(9),
    denominationunitelegale VARCHAR(255),
    categoriejuridiqueunitelegale VARCHAR(10),
    activiteprincipaleunitelegale VARCHAR(10)
);

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

DROP VIEW IF EXISTS v_index_usage CASCADE;
CREATE VIEW v_index_usage AS
SELECT
    s.schemaname,
    s.relname,
    s.indexrelname,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size
FROM pg_stat_user_indexes s
ORDER BY s.schemaname, s.relname, s.indexrelname;

DROP VIEW IF EXISTS v_table_stats CASCADE;
CREATE VIEW v_table_stats AS
SELECT
    s.schemaname,
    s.relname,
    s.seq_scan,
    s.idx_scan,
    pg_size_pretty(pg_total_relation_size(format('%I.%I', s.schemaname, s.relname))) AS total_size,
    pg_size_pretty(pg_relation_size(format('%I.%I', s.schemaname, s.relname))) AS table_size,
    pg_size_pretty(pg_indexes_size(format('%I.%I', s.schemaname, s.relname))) AS indexes_size,
    s.n_tup_ins, s.n_tup_upd, s.n_tup_del
FROM pg_stat_user_tables s
ORDER BY s.schemaname, s.relname;
