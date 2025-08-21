-- Jeu de données moyen (~50k lignes) pour démos rapides


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

-- Ligne de référence exacte (coordonnées spécifiques)
INSERT INTO referentiels.adresse_postale (numero, nom_voie, nom_commune, code_post, lat, lon)
VALUES (15, 'rue des jacinthes', 'Nancy', '54000', 49.100550230878, 6.18587523388308)
ON CONFLICT DO NOTHING;

WITH base AS (
    SELECT
        (1 + (random()*999)::int) AS numero,
        CASE 
            WHEN random() < 0.03 THEN 'rue des jacinthes'
            WHEN random() < 0.06 THEN 'avenue de la République'
            ELSE (ARRAY['rue Victor Hugo','avenue des Tests','boulevard de la Liberté','rue Nationale','rue de la Gare'])[1 + (random()*4)::int]
        END AS nom_voie,
        CASE
            WHEN random() < 0.30 THEN 'Nancy'
            WHEN random() < 0.20 THEN 'Paris'
            WHEN random() < 0.15 THEN 'Lyon'
            WHEN random() < 0.15 THEN 'Marseille'
            WHEN random() < 0.10 THEN 'Toulouse'
            ELSE 'Metz'
        END AS nom_commune,
        (48.0 + random()*3)::numeric(15,12) AS lat,
        (2.0 + random()*6)::numeric(15,12) AS lon
    FROM generate_series(1, 50000)
)
INSERT INTO referentiels.adresse_postale (numero, nom_voie, nom_commune, code_post, lat, lon)
SELECT
    numero,
    nom_voie,
    nom_commune,
    CASE
        WHEN nom_commune='Nancy' THEN '54000'
        WHEN nom_commune='Paris' THEN '75001'
        WHEN nom_commune='Lyon' THEN '69001'
        WHEN nom_commune='Marseille' THEN '13001'
        WHEN nom_commune='Toulouse' THEN '31000'
        ELSE '57000'
    END AS code_post,
    lat,
    lon
FROM base;
