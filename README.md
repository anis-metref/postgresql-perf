# SQL - Base de données (Étude des performances de PostgreSQL)

Application streamlit (python) et scripts pour installer un environnement postgresql, charger des données, visualiser des statistiques et réaliser des benchmarks (pgbench).

## Présentation
Ce projet propose:
- une application streamlit de visualisation et d'expérimentation autour des performances postgresql,
- un script Bash interactif pour installer/configurer postgresql (cluster dédié), restaurer des sauvegardes et lancer l'application.

## Fonctionnalités
- Tableau de bord: métriques et graphiques (barres, lignes, aires), comparatif avec/sans index.
- Requêtes et index: exécution libre, création d'index utiles, mini-benchmarks avant/après index.
- Charge (pgbench): exécution simple et campagnes multi-clients par profil (impact hardware/tuning), export CSV.
- Monitoring: vues v_index_usage et v_table_stats (créées par le bootstrap) pour suivre l'utilisation des index et la taille des tables.
- Chargement de données: scripts intégrés pour structure minimale et jeux de données de différentes tailles.

## Prérequis
- Linux (Debian/Ubuntu recommandés) avec sudo pour le script d'installation.
- Python 3.9+, python3-pip, python3-venv, git
- Postgresql (13, 15..)

## Installation rapide (script Bash)
1.  Clonez ce dépôt en utilisant la commande suivante :
```
git clone https://github.com/anis-metref/postgresql-perf.git
cd postgresql-perf
```
Le script gère l'installation PostgreSQL, la création d'un cluster dédié, la configuration réseau locale 

1) Exécuter le script avec droits root:
```
chmod +x ./setup_env.sh
sudo ./setup_env.sh
```
2) Dans le menu:
- 1 ) Installer PostgreSQL et créer cluster
- 5 ) Créer la base tp3Perf
- 6 ) Bootstrap SQL (structure minimale)
- 7 ) Charger données d'exemple OU 8) Charger données conséquentes OU "Données moyen volume" depuis l'app
- 12 ) Lancer l'application Streamlit

## Lancer l'application (manuel)
Sans passer par le script Bash:
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run main.py
```

Acceder depuis le navigateur : http://votreip:8501 
Puis configurer la connexion postgresql dans la barre latérale de l'app.

## Données sql
Scripts intégrés (barre latérale de l'app):
- Structure minimale: /sql/bootstrap.sql
- Données d'exemple: /sql/sample_data.sql
- Données moyen volume (~50k): /sql/data_moyen.sql
- Données conséquentes (~300k): /sql/data.sql
- Vous pouvez aussi charger un script .sql personnalisé (uploader dans la barre latérale).

Conseil:
- Commencez avec data_moyen.sql pour des démos rapides.
- Utilisez la section "Nettoyage des données" (onglet Tableau de bord) pour vider les tables et recharger un autre jeu.

## Benchmarks et monitoring
- Onglet "Requêtes et index":
  - Benchmarks avant/après index sur 2 requêtes typiques (égalité texte, lat/lon) avec tableau et graphes comparatifs.
- Onglet "Charge (pgbench)":
  - Exécution simple: affiche la commande, la sortie, et alimente les graphes TPS/latence.
  - Campagne multi-clients par profil (ex: "2GB RAM, tuning A"): table de résultats, courbes TPS/latence, barres comparatives par profil, export CSV.
- Onglet "Monitoring":
  - Visualisation des vues v_index_usage et v_table_stats.

## Nettoyage des données
Onglet "Tableau de bord": section "Nettoyage des données":
- Liste des tables visées (referentiels.adresse_postale, referentiels.etablissement, referentiels.unite_legale) et volumes actuels.
- Bouton pour TRUNCATE ... RESTART IDENTITY sur ces tables, puis recharger un autre .sql.

## Dépannage
- Authentification PostgreSQL:
  - Il n'y a pas de mot de passe par défaut pour l'utilisateur postgres. En local, vous pouvez définir un mot de passe:
    ```sql
    sudo -u postgres psql
    ALTER USER postgres PASSWORD 'VotreMotDePasseSolide';
    ```
  - Dans l'app, utilisez l'hôte 127.0.0.1 (évite IPv6 ::1 si pg_hba.conf n'est pas configuré) et renseignez le mot de passe.
- Vues de monitoring: si vous voyez "cannot drop columns from view", rejouez le bootstrap (les scripts suppriment désormais les vues puis les recréent):
  ```
  sudo -u postgres psql -d tp3Perf -f projet/sql/bootstrap.sql
  ```
- pgbench absent:
  - Installez postgresql-client et postgresql-contrib via le menu 1) ou apt:
    ```
    sudo apt-get install -y postgresql-client postgresql-contrib
    ```
- Service/cluster:
  - Vérifiez l'état via le menu 11) du setup ou:
    ```
    sudo pg_lsclusters
    sudo systemctl status postgresql@<version>-<cluster>
    ```

## Structure du dépôt
- main.py: application Streamlit
- setup_env.sh: script d'installation/gestion avec menu
- sql/*.sql: scripts SQL intégrés (structure, données)
- requirements.txt: dépendances Python


<!-- Styles -->
<style>
.slider {
  position: relative;
  max-width: 900px;
  margin: auto;
  overflow: hidden;
}

.slides {
  display: flex;
  transition: transform 0.5s ease-in-out;
}

.card {
  flex: 0 0 100%;
  background: #fcf7f7ff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(0,0,0,0.1);
  display: flex;
  flex-direction: column;
}

.card img.img-full {
  width: 100%;
  display: block;
}

/* Description avec fond plus contrasté et ombre renforcée */
.card .desc {
  padding: 20px;
  background: #eaeaea; /* gris cassé plus foncé */
  font-family: "Segoe UI", sans-serif;
  color: #141412ff;
  text-align: center;
  border-radius: 8px;
  box-shadow: 0 6px 16px rgba(0,0,0,0.2); /* ombre plus visible */
}

.card .desc h3 {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 8px;
  color: #131eafff;
}

.card .desc p {
  font-size: 15px;
  line-height: 1.5;
  color: #2c2424ff;
  margin: 0;
}

.arrow {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: 28px;
  color: white;
  background: rgba(0, 0, 0, 0.4);
  border: none;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 50%;
  z-index: 10;
}

.arrow:hover {
  background: rgba(22, 21, 21, 0.7);
}

.arrow.left {
  left: 10px;
}

.arrow.right {
  right: 10px;
}

.dots {
  text-align: center;
  margin-top: 12px;
}

.dot {
  height: 12px;
  width: 12px;
  margin: 0 5px;
  background-color: #bbb;
  border-radius: 50%;
  display: inline-block;
  cursor: pointer;
  transition: background-color 0.3s;
}

.dot.active {
  background-color: #24244dff;
}
</style>

<!-- HTML -->
<div class="slider">
  <button class="arrow left" onclick="changeSlide(-1)">&#10094;</button>
  <div class="slides" id="slides">
    <div class="card">
      <img src="screenshot.png" alt="Dashboard Apache2" class="img-full">
      <div class="desc">
        <h3>Analyse apache2</h3>
        <p>Visualisation des accès et erreurs pour détecter les comportements suspects sur un serveur web</p>
      </div>
    </div>
    <div class="card">
      <img src="screenshot.png" alt="Dashboard Suricata" class="img-full">
      <div class="desc">
        <h3>Surveillance suricata</h3>
        <p>Détection avancée des menaces réseau grâce à des règles ips/ids</p>
      </div>
    </div>
    <div class="card">
      <img src="screenshot.png"" alt="Dashboard Système" class="img-full">
      <div class="desc">
        <h3>Logs système</h3>
        <p>Suivi en temps réel des événements système</p>
      </div>
    </div>
  </div>
  <button class="arrow right" onclick="changeSlide(1)">&#10095;</button>
</div>

<div class="dots" id="dots">
  <span class="dot active" onclick="currentSlide(0)"></span>
  <span class="dot" onclick="currentSlide(1)"></span>
  <span class="dot" onclick="currentSlide(2)"></span>
</div>

<!-- JS -->
<script>
let index = 0;
const slides = document.getElementById('slides');
const dots = document.querySelectorAll('.dot');
const total = dots.length;

function showSlide(i) {
  index = (i + total) % total;
  slides.style.transform = 'translateX(' + (-index * 100) + '%)';
  dots.forEach(dot => dot.classList.remove('active'));
  dots[index].classList.add('active');
}

function changeSlide(step) {
  showSlide(index + step);
}

function currentSlide(i) {
  showSlide(i);
}
</script>
