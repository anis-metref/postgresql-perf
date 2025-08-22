-- Données d'exemple minimales
INSERT INTO referentiels.adresse_postale (numero, nom_voie, nom_commune, code_post, lat, lon)
VALUES
  (15, 'rue des jacinthes', 'Metz', '57000', 49.100550230878, 6.18587523388308),
  (23, 'avenue des Tests', 'Paris', '75001', 48.8566, 2.3522)
ON CONFLICT DO NOTHING;

INSERT INTO referentiels.unite_legale (siren, denominationunitelegale, categoriejuridiqueunitelegale, activiteprincipaleunitelegale)
VALUES ('440363588', 'Société Test SARL', '5710', '6201Z')
ON CONFLICT DO NOTHING;

INSERT INTO referentiels.etablissement (siren, siret, numerovoieetablissement, denominationunitelegale)
VALUES ('440363588', '44036358800015', 15, 'Société Test SARL')
ON CONFLICT DO NOTHING;
