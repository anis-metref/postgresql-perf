#!/usr/bin/env bash
# Script de mise en place de l'environnement PostgreSQL + App Streamlit

set -Eeuo pipefail

# Couleurs
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$APP_DIR/setup_env.log"
PG_VERSION="15"
CLUSTER_NAME="projet_perf"
DB_NAME="tp3Perf"
LISTEN_ADDR="127.0.0.1"
ALLOW_CIDR=""

log(){ echo "[$(date +'%F %T')] $*" | tee -a "$LOG_FILE"; }
info(){ echo -e "${CYAN}$*${NC}" | tee -a "$LOG_FILE"; }
success(){ echo -e "${GREEN}$*${NC}" | tee -a "$LOG_FILE"; }
warn(){ echo -e "${YELLOW}$*${NC}" | tee -a "$LOG_FILE"; }
error(){ echo -e "${RED}$*${NC}" | tee -a "$LOG_FILE"; }
step(){ echo -e "${BLUE}==> $*${NC}" | tee -a "$LOG_FILE"; }

confirm(){ local msg="$1"; local ans; read -rp "$msg [y/N]: " ans || true; [[ "$ans" =~ ^[Yy]$ ]]; }

run(){
  local desc="$1"; shift
  step "$desc"
  echo "+ $*" | tee -a "$LOG_FILE"
  "$@" 2>&1 | tee -a "$LOG_FILE" || { rc=${PIPESTATUS[0]}; error "Échec ($rc): $desc"; exit $rc; }
  success "OK: $desc"
}

pa(){ read -rp "Appuyez sur Entrée pour continuer..." x; }

ensure_bash(){ if [ -z "${BASH_VERSION:-}" ]; then exec /usr/bin/env bash "$0" "$@"; fi; }
ensure_bash "$@"

check_root(){ if [[ $EUID -ne 0 ]]; then error "Exécuter avec sudo/root"; exit 1; fi; }

install_postgres(){
  if command -v psql &>/dev/null; then
    v=$(psql --version | awk '{print $3}')
    info "PostgreSQL déjà installé (version $v)"
    if ! confirm "Voulez-vous réinstaller/mettre à niveau vers $PG_VERSION ?"; then return; fi
  fi
  run "Mise à jour des paquets" apt-get update -y
  run "Installation prérequis" apt-get install -y wget curl gnupg2 ca-certificates lsb-release
  run "Ajout clé PGDG" install -d /usr/share/keyrings
  curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg
  CODENAME=$(lsb_release -cs)
  echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list
  run "Mise à jour dépôt PGDG" apt-get update -y
  run "Installation PostgreSQL $PG_VERSION" apt-get install -y postgresql-$PG_VERSION postgresql-client-$PG_VERSION postgresql-contrib-$PG_VERSION
}

create_cluster(){
  info "Vérification cluster $PG_VERSION/$CLUSTER_NAME"
  if command -v pg_lsclusters &>/dev/null && pg_lsclusters | awk '{print $1" "$2}' | grep -q "^$PG_VERSION $CLUSTER_NAME$"; then
    success "Cluster déjà présent"
    return
  fi
  run "Création du cluster $PG_VERSION/$CLUSTER_NAME" sudo -u postgres pg_createcluster --locale C.UTF-8 "$PG_VERSION" "$CLUSTER_NAME"
  run "Enable service" systemctl enable postgresql@${PG_VERSION}-${CLUSTER_NAME}.service
  run "Démarrage du cluster" pg_ctlcluster "$PG_VERSION" "$CLUSTER_NAME" start
}

config_pg(){
  CONF="/etc/postgresql/${PG_VERSION}/${CLUSTER_NAME}/postgresql.conf"
  HBA="/etc/postgresql/${PG_VERSION}/${CLUSTER_NAME}/pg_hba.conf"
  if [[ ! -f "$CONF" ]]; then warn "Fichier $CONF introuvable"; return; fi
  step "Configuration de $CONF"
  sed -i "s/^#\?listen_addresses.*/listen_addresses='${LISTEN_ADDR//\//\/}'/" "$CONF" || true
  if [[ -n "$ALLOW_CIDR" ]]; then echo "host all all ${ALLOW_CIDR} scram-sha-256" >> "$HBA"; fi
  if ! grep -qE "^host\s+all\s+all\s+127.0.0.1/32" "$HBA"; then echo "host all all 127.0.0.1/32 scram-sha-256" >> "$HBA"; fi
  if ! grep -qE "^host\s+all\s+all\s+::1/128" "$HBA"; then echo "host all all ::1/128 scram-sha-256" >> "$HBA"; fi
  run "Redémarrage du cluster" systemctl restart postgresql@${PG_VERSION}-${CLUSTER_NAME}.service
}

show_status(){
  echo
  step "Etat de l'environnement"
  if command -v psql &>/dev/null; then
    v=$(psql --version | awk '{print $3}'); info "PostgreSQL installé: ${v}";
  else
    warn "PostgreSQL non installé"
  fi
  if command -v pg_lsclusters &>/dev/null; then
    info "Clusters:"; pg_lsclusters | tee -a "$LOG_FILE"
  else
    warn "pg_lsclusters indisponible"
  fi
  UNIT="postgresql@${PG_VERSION}-${CLUSTER_NAME}.service"
  if systemctl is-active --quiet "$UNIT"; then success "Service ${UNIT} actif"; else warn "Service ${UNIT} inactif"; fi
  if sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    success "Base ${DB_NAME} présente"
  else
    warn "Base ${DB_NAME} absente"
  fi
  CONF="/etc/postgresql/${PG_VERSION}/${CLUSTER_NAME}/postgresql.conf"
  if [[ -f "$CONF" ]]; then
    cur=$(grep -E "^listen_addresses\s*=\s*" "$CONF" | head -1 | cut -d= -f2-)
    info "listen_addresses: ${cur}"
  fi
  echo
}

create_db(){
  step "Création DB ${DB_NAME}"
  if sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    success "Base déjà existante"
  else
    run "Création de la base ${DB_NAME}" sudo -u postgres createdb "$DB_NAME"
  fi
}

restore_backup(){
  echo "Restaurer une sauvegarde (fichier .sql ou .dump)"
  read -rp "Chemin du fichier: " FILE
  if [[ -z "$FILE" || ! -f "$FILE" ]]; then echo "Fichier invalide"; return; fi
  case "$FILE" in
    *.sql) sudo -u postgres psql -d "$DB_NAME" -f "$FILE";;
    *.dump|*.custom) sudo -u postgres pg_restore -d "$DB_NAME" "$FILE";;
    *) echo "Extension non supportée";;
  esac
}

bootstrap_sql(){
  if [[ ! -f "$APP_DIR/sql/bootstrap.sql" ]]; then warn "bootstrap.sql introuvable"; return; fi
  run "Bootstrap SQL (structure minimale)" sudo -u postgres psql -d "$DB_NAME" -f "$APP_DIR/sql/bootstrap.sql"
}

sample_data(){
  if [[ ! -f "$APP_DIR/sql/sample_data.sql" ]]; then warn "sample_data.sql introuvable"; return; fi
  run "Chargement données d'exemple" sudo -u postgres psql -d "$DB_NAME" -f "$APP_DIR/sql/sample_data.sql"
}

start_service(){ systemctl start postgresql@${PG_VERSION}-${CLUSTER_NAME}.service || true; }
stop_service(){ systemctl stop postgresql@${PG_VERSION}-${CLUSTER_NAME}.service || true; }
restart_service(){ systemctl restart postgresql@${PG_VERSION}-${CLUSTER_NAME}.service || true; }
reinstall_all(){
  warn "Cette opération supprimera PostgreSQL et toutes les données locales."
  if ! confirm "Confirmez-vous la réinstallation complète ?"; then return; fi
  run "Arrêt service PostgreSQL" systemctl stop postgresql
  run "Purge paquets PostgreSQL" apt-get remove --purge -y postgresql*
  run "Autoremove" apt-get autoremove -y
  run "Suppression répertoires" rm -rf /var/lib/postgresql /etc/postgresql /var/log/postgresql
  install_postgres
  create_cluster
  config_pg
}

menu(){
  clear
  echo -e "${BLUE}SQL - Base de données (Étude des performances de PostgreSQL)${NC}"
  echo -e "${YELLOW}1)${NC} Installer PostgreSQL et créer cluster"
  echo -e "${YELLOW}2)${NC} Démarrer service"
  echo -e "${YELLOW}3)${NC} Arrêter service"
  echo -e "${YELLOW}4)${NC} Redémarrer service"
  echo -e "${YELLOW}5)${NC} Créer base ${DB_NAME}"
  echo -e "${YELLOW}6)${NC} Bootstrap SQL (structure minimale)"
  echo -e "${YELLOW}7)${NC} Charger données d'exemple"
  echo -e "${YELLOW}8)${NC} Charger données conséquentes (data.sql)"
  echo -e "${YELLOW}9)${NC} Restaurer une sauvegarde (.sql/.dump)"
  echo -e "${YELLOW}10)${NC} Réinstaller tout (purge + install)"
  echo -e "${YELLOW}11)${NC} Afficher l'état (diagnostic)"
  echo -e "${YELLOW}12)${NC} Lancer l'application Streamlit"
  echo -e "${YELLOW}0)${NC} Quitter"
  read -rp "> Choix: " ch
  case "$ch" in
    1) info "Vous allez installer PostgreSQL ${PG_VERSION} et créer le cluster ${CLUSTER_NAME}"; install_postgres; create_cluster; config_pg; pa;;
    2) info "Vous allez démarrer le service postgresql@${PG_VERSION}-${CLUSTER_NAME}"; start_service; pa;;
    3) info "Vous allez arrêter le service postgresql@${PG_VERSION}-${CLUSTER_NAME}"; stop_service; pa;;
    4) info "Vous allez redémarrer le service postgresql@${PG_VERSION}-${CLUSTER_NAME}"; restart_service; pa;;
    5) info "Vous allez créer la base ${DB_NAME}"; create_db; pa;;
    6) info "Vous allez appliquer le bootstrap SQL"; bootstrap_sql; pa;;
    7) info "Vous allez charger des données d'exemple"; sample_data; pa;;
    8) info "Vous allez charger des données conséquentes (data.sql)"; if [[ -f "$APP_DIR/sql/data.sql" ]]; then run "Chargement data.sql" sudo -u postgres psql -d "$DB_NAME" -f "$APP_DIR/sql/data.sql"; else warn "data.sql absent"; fi; pa;;
    9) info "Vous allez restaurer une sauvegarde"; restore_backup; pa;;
    10) info "Vous allez réinstaller complètement PostgreSQL"; reinstall_all; pa;;
    11) show_status; pa;;
    12) run_app; pa;;
    0) exit 0;;
    *) echo "Choix invalide"; pa;;
  esac
}

run_app(){
  log "Lancement de l'application Streamlit"
  if ! command -v streamlit &>/dev/null; then
    echo "Installation des dépendances Python (user local)"
    python3 -m pip install --user -r "$APP_DIR/requirements.txt"
  fi
  streamlit run "$APP_DIR/main.py"
}

main(){
  check_root
  while true; do menu; done
}

main "$@"
