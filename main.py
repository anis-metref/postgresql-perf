import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

# Optional plotting libs
try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except Exception:
    PLOTLY_AVAILABLE = False
from pathlib import Path
import time
import io
import subprocess
import shutil
import re

# -----------------------------
# Configuration
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = PROJECT_ROOT / "projet" / "sql"
SQL_FILES = {
    "Structure minimale": SQL_DIR / "bootstrap.sql",
    "Données d'exemple": SQL_DIR / "sample_data.sql",
    "Données moyen volume": SQL_DIR / "data_moyen.sql",
    "Données conséquentes": SQL_DIR / "data.sql",
}

DEFAULT_QUERIES = {
    "Top 10 communes": """
        SELECT nom_commune, COUNT(*) AS nb
        FROM referentiels.adresse_postale
        GROUP BY nom_commune
        ORDER BY nb DESC
        LIMIT 10;
    """,
    "Top 10 voies": """
        SELECT nom_voie, COUNT(*) AS nb
        FROM referentiels.adresse_postale
        GROUP BY nom_voie
        ORDER BY nb DESC
        LIMIT 10;
    """,
    "Top 15 codes postaux": """
        SELECT code_post, COUNT(*) AS nb
        FROM referentiels.adresse_postale
        GROUP BY code_post
        ORDER BY nb DESC
        LIMIT 15;
    """,
}

# -----------------------------
# Helpers
# -----------------------------

def _connect(params: dict):
    conn = psycopg2.connect(
        host=params.get("host", "127.0.0.1"),
        port=int(params.get("port", 5432)),
        dbname=params.get("dbname", "tp3Perf"),
        user=params.get("user", "postgres"),
        password=params.get("password", ""),
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = True
    return conn


def query_df(conn, q: str, params=None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(q, params or {})
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def clean_sql(sql_text: str) -> str:
    cleaned_lines = []
    for line in io.StringIO(sql_text):
        l = line.strip()
        if not l:
            continue
        if l.startswith("--"):
            continue
        if l.startswith("\\"):
            continue
        cleaned_lines.append(line)
    return "".join(cleaned_lines)


def execute_sql_script(conn, sql_text: str):
    with conn.cursor() as cur:
        cur.execute(sql_text)


def run_known_script(conn, label: str):
    path = SQL_FILES.get(label)
    if not path or not path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {path}")
    sql_text = clean_sql(path.read_text(encoding="utf-8"))
    execute_sql_script(conn, sql_text)


def list_tables(conn, schema: str) -> pd.DataFrame:
    q = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_type='BASE TABLE'
        ORDER BY table_name;
    """
    return query_df(conn, q, (schema,))


def estimated_counts(conn, schema: str) -> pd.DataFrame:
    q = """
        SELECT c.relname AS table_name, c.reltuples::bigint AS estimated_rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind='r'
        ORDER BY 1;
    """
    return query_df(conn, q, (schema,))


def exact_count_for_table(conn, schema: str, table: str) -> int:
    try:
        df = query_df(conn, f"SELECT COUNT(*) AS nb FROM {schema}.{table};")
        return int(df["nb"].iloc[0])
    except Exception:
        return None


def explain_cost(conn, query: str):
    try:
        df = query_df(conn, "EXPLAIN " + query)
        if not df.empty:
            text = list(df.iloc[0].values())[0]
            m = re.search(r"cost=([0-9.]+)\.\.([0-9.]+)", str(text))
            if m:
                return float(m.group(1)), float(m.group(2))
    except Exception:
        return None
    return None


def measure_query_time(conn, query: str) -> float:
    tic = time.perf_counter()
    _ = query_df(conn, query)
    toc = time.perf_counter()
    return toc - tic


def create_index_if_not_exists(conn, index_sql: str):
    with conn.cursor() as cur:
        cur.execute(index_sql)


def parse_pgbench_output(out: str) -> dict:
    # Supporte variantes: "tps = X (including connections establishing)" et "tps = X (without initial connection time)"
    # et "latency average = Y ms", "initial connection time = Z ms"
    import re
    result = {
        "tps_incl": None,
        "tps_excl": None,
        "latency_avg_ms": None,
        "initial_conn_ms": None,
        "processed": None,
        "failed": None,
    }
    for line in out.splitlines():
        line = line.strip()
        m = re.search(r"^tps\s*=\s*([0-9]+\.?[0-9]*)\s*\(([^)]*)\)", line)
        if m:
            val = float(m.group(1))
            note = m.group(2).lower()
            if "without" in note or "excluding" in note:
                result["tps_excl"] = val
            else:
                result["tps_incl"] = val
        m = re.search(r"latency average\s*=\s*([0-9]+\.?[0-9]*)\s*ms", line)
        if m:
            result["latency_avg_ms"] = float(m.group(1))
        m = re.search(r"initial connection time\s*=\s*([0-9]+\.?[0-9]*)\s*ms", line)
        if m:
            result["initial_conn_ms"] = float(m.group(1))
        m = re.search(r"number of transactions actually processed:\s*([0-9]+)", line)
        if m:
            result["processed"] = int(m.group(1))
        m = re.search(r"number of failed transactions:\s*([0-9]+)", line)
        if m:
            result["failed"] = int(m.group(1))
    return result


def count_table_safe(conn, qualified_name: str) -> int | None:
    try:
        df = query_df(conn, f"SELECT COUNT(*) AS nb FROM {qualified_name};")
        return int(df["nb"].iloc[0])
    except Exception:
        return None


def existing_tables_in(conn, schema: str, candidates: list[str]) -> list[str]:
    try:
        df = list_tables(conn, schema)
        avail = set(df.table_name.tolist())
        return [f"{schema}.{t}" for t in candidates if t in avail]
    except Exception:
        return []


def truncate_tables(conn, tables: list[str]):
    if not tables:
        return
    stmt = "TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY;"
    with conn.cursor() as cur:
        cur.execute(stmt)

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="SQL - Base de données (Étude des performances de PostgreSQL)", layout="wide")

# Theme and CSS helpers for a compact, global dashboard view
PALETTE = [
    "#00b4d8", "#90e0ef", "#ffd60a", "#e85d04", "#6a4c93", "#2a9d8f",
    "#ff6b6b", "#4cc9f0", "#f72585", "#b5179e"
]

def style_fig(fig, height: int = 260):
    try:
        fig.update_layout(
            height=height,
            template="plotly_white",
            margin=dict(l=30, r=20, t=40, b=30),
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            font=dict(family="Inter, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica Neue, Arial, \"Apple Color Emoji\", \"Segoe UI Emoji\"", size=12, color="#0f172a"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        # Apply a consistent colorway
        fig.update_layout(colorway=PALETTE)
    except Exception:
        pass
    return fig

# Base CSS (compact paddings)
st.markdown(
    """
    <style>
    .block-container {padding-top: 0.75rem; padding-bottom: 0.5rem;}
    .element-container {margin-bottom: 0.5rem;}
    .stTabs [data-baseweb="tab-list"] {gap: 8px;}
    .stMetric {background: #0f172a10; color: #0f172a; padding: 10px 12px; border-radius: 8px; border: 1px solid #e2e8f0;}
    .st-emotion-cache-1kyxreq {padding: 0.25rem 0.5rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("SQL - Base de données (Étude des performances de PostgreSQL)")

st.sidebar.header("Connexion PostgreSQL")
def_conn = {
    "host": st.sidebar.text_input("Hôte", value="127.0.0.1"),
    "port": st.sidebar.number_input("Port", value=5432, step=1),
    "dbname": st.sidebar.text_input("Base de données", value="tp3Perf"),
    "user": st.sidebar.text_input("Utilisateur", value="postgres"),
    "password": st.sidebar.text_input("Mot de passe", value="", type="password"),
}

# UI options
view_compact = st.sidebar.checkbox("Vue globale compacte (sans scroll)", value=True,
                                   help="Active une mise en page en grille et des graphiques compacts pour tenir sur un écran.")
st.session_state["view_compact"] = view_compact

if "conn" not in st.session_state:
    st.session_state.conn = None
st.session_state.conn_params = def_conn

colA, colB = st.sidebar.columns(2)
if colA.button("Se connecter", use_container_width=True):
    try:
        st.session_state.conn = _connect(def_conn)
        st.sidebar.success("Connexion établie")
    except Exception as e:
        st.session_state.conn = None
        st.sidebar.error(f"Échec connexion: {e}")

if colB.button("Se déconnecter", use_container_width=True):
    try:
        if st.session_state.conn:
            st.session_state.conn.close()
    finally:
        st.session_state.conn = None
        st.sidebar.info("Déconnecté")

conn = st.session_state.conn

# Actions scripts SQL
st.sidebar.header("Scripts SQL intégrés")
if st.sidebar.button("Créer structure minimale", disabled=not conn, use_container_width=True):
    try:
        run_known_script(conn, "Structure minimale")
        st.sidebar.success("Structure créée")
    except Exception as e:
        st.sidebar.error(str(e))

if st.sidebar.button("Charger données d'exemple", disabled=not conn, use_container_width=True):
    try:
        run_known_script(conn, "Données d'exemple")
        st.sidebar.success("Données chargées")
    except Exception as e:
        st.sidebar.error(str(e))

uploaded = st.sidebar.file_uploader("Exécuter un script SQL personnalisé (.sql)", type=["sql"], disabled=not conn)
if uploaded is not None and conn:
    try:
        sql_text = uploaded.read().decode("utf-8")
        execute_sql_script(conn, clean_sql(sql_text))
        st.sidebar.success("Script exécuté")
    except Exception as e:
        st.sidebar.error(str(e))

# Onglets
Tab1, Tab2, Tab3, Tab4, Tab5 = st.tabs([
    "Tableau de bord",
    "Requêtes et index",
    "Charge (pgbench)",
    "Monitoring",
    "Aide",
])

with Tab1:
    st.subheader("Dashboard global")
    if not conn:
        st.info("Connectez-vous pour afficher les statistiques.")
    else:
        # Nettoyage: expander pour ne pas occuper la hauteur
        with st.expander("Nettoyage des données chargées", expanded=not st.session_state.get("view_compact", True)):
            candidates = existing_tables_in(conn, "referentiels", ["adresse_postale", "etablissement", "unite_legale"])
            if candidates:
                counts = {t: count_table_safe(conn, t) for t in candidates}
                st.write("Les tables suivantes seront vidées (TRUNCATE RESTART IDENTITY):")
                st.json(counts)
                if st.button("Vider ces tables"):
                    try:
                        truncate_tables(conn, candidates)
                        st.success("Tables vidées. Vous pouvez charger un autre .sql moyen/conséquent.")
                    except Exception as e:
                        st.error(str(e))
            else:
                st.caption("Aucune table cible trouvée dans le schéma referentiels.")

        # Métriques clés
        def count_table(tbl):
            try:
                df = query_df(conn, f"SELECT COUNT(*) AS nb FROM {tbl};")
                return int(df["nb"].iloc[0])
            except Exception:
                return None
        mcol1, mcol2, mcol3 = st.columns(3)
        nb_addr = count_table("referentiels.adresse_postale")
        nb_eta = count_table("referentiels.etablissement")
        nb_ul = count_table("referentiels.unite_legale")
        mcol1.metric("Adresses", nb_addr if nb_addr is not None else "-")
        mcol2.metric("Établissements", nb_eta if nb_eta is not None else "-")
        mcol3.metric("Unités légales", nb_ul if nb_ul is not None else "-")

        # Row 1: Top 10/15
        c1, c2, c3 = st.columns(3)
        # Top 10 communes
        try:
            df_communes = query_df(conn, DEFAULT_QUERIES["Top 10 communes"]).rename(columns={"nom_commune":"lib", "nb":"val"})
            if not df_communes.empty:
                if PLOTLY_AVAILABLE:
                    import plotly.express as px
                    fig = px.bar(df_communes.sort_values("val"), x="val", y="lib", orientation="h", title="Top 10 communes")
                    fig.update_yaxes(categoryorder="array", categoryarray=df_communes.sort_values("val")["lib"].tolist())
                    c1.plotly_chart(style_fig(fig, height=260), use_container_width=True)
                else:
                    with c1:
                        st.bar_chart(df_communes.set_index("lib"))
        except Exception as e:
            st.warning(f"Top 10 communes: {e}")
        # Top 10 voies
        try:
            df_voies = query_df(conn, DEFAULT_QUERIES["Top 10 voies"]).rename(columns={"nom_voie":"lib", "nb":"val"})
            if not df_voies.empty:
                if PLOTLY_AVAILABLE:
                    import plotly.express as px
                    fig = px.bar(df_voies.sort_values("val"), x="val", y="lib", orientation="h", title="Top 10 voies")
                    fig.update_yaxes(categoryorder="array", categoryarray=df_voies.sort_values("val")["lib"].tolist())
                    c2.plotly_chart(style_fig(fig, height=260), use_container_width=True)
                else:
                    with c2:
                        st.bar_chart(df_voies.set_index("lib"))
        except Exception as e:
            st.warning(f"Top 10 voies: {e}")
        # Top 15 codes postaux
        try:
            df_cp = query_df(conn, DEFAULT_QUERIES["Top 15 codes postaux"]).rename(columns={"code_post":"lib", "nb":"val"})
            if not df_cp.empty:
                if PLOTLY_AVAILABLE:
                    import plotly.express as px
                    fig = px.bar(df_cp.sort_values("val"), x="lib", y="val", title="Top 15 codes postaux")
                    c3.plotly_chart(style_fig(fig, height=260), use_container_width=True)
                else:
                    with c3:
                        st.bar_chart(df_cp.set_index("lib"))
        except Exception as e:
            st.warning(f"Top 15 codes postaux: {e}")

        # Row 2: comparatif avec/sans index + donut
        st.markdown("Comparatif: 'rue des jacinthes' (avec vs sans index)")
        q_jac = "SELECT nom_commune, code_post FROM referentiels.adresse_postale WHERE nom_voie = 'rue des jacinthes';"
        try:
            d1 = measure_query_time(conn, q_jac)
        except Exception:
            d1 = None
        try:
            create_index_if_not_exists(conn, "CREATE INDEX IF NOT EXISTS idx_adresse_nom_voie ON referentiels.adresse_postale (nom_voie);")
            d2 = measure_query_time(conn, q_jac)
        except Exception:
            d2 = None
        data_comp = []
        if d1 is not None: data_comp.append({"version": "sans index", "ms": d1*1000})
        if d2 is not None: data_comp.append({"version": "avec index", "ms": d2*1000})
        if data_comp:
            df_comp = pd.DataFrame(data_comp)
            colL, colR = st.columns(2)
            if PLOTLY_AVAILABLE:
                import plotly.express as px
                fig_bar = px.bar(df_comp, x="version", y="ms", color="version", title="Temps (ms)")
                colL.plotly_chart(style_fig(fig_bar, height=260), use_container_width=True)
                fig_pie = px.pie(df_comp, values="ms", names="version", hole=0.5, title="Répartition du temps")
                colR.plotly_chart(style_fig(fig_pie, height=260), use_container_width=True)
            else:
                colL.bar_chart(df_comp.set_index("version"))

        # Extras: tendances dans un expander si compact
        if not st.session_state.get("view_compact", True):
            with st.expander("Tendances supplémentaires", expanded=True):
                try:
                    df_cp2 = query_df(conn, """
                        SELECT code_post, COUNT(*)::int AS nb
                        FROM referentiels.adresse_postale
                        GROUP BY code_post
                        ORDER BY code_post
                        LIMIT 100
                    """)
                    if not df_cp2.empty and PLOTLY_AVAILABLE:
                        import plotly.express as px
                        fig_line = px.line(df_cp2, x="code_post", y="nb", title="Distribution par code postal (limité)")
                        st.plotly_chart(style_fig(fig_line, height=260), use_container_width=True)
                    elif not df_cp2.empty:
                        st.line_chart(df_cp2.set_index("code_post"))
                except Exception:
                    pass
                try:
                    df_top = query_df(conn, """
                        SELECT nom_commune, COUNT(*)::int AS nb
                        FROM referentiels.adresse_postale
                        GROUP BY nom_commune
                        ORDER BY nb DESC
                        LIMIT 20
                    """)
                    if not df_top.empty and PLOTLY_AVAILABLE:
                        import plotly.express as px
                        fig_area = px.area(df_top, x="nom_commune", y="nb", title="Top communes (aire)")
                        st.plotly_chart(style_fig(fig_area, height=260), use_container_width=True)
                    elif not df_top.empty:
                        st.area_chart(df_top.set_index("nom_commune"))
                except Exception:
                    pass

with Tab2:
    st.subheader("Requêtes et index")
    if not conn:
        st.info("Connectez-vous pour exécuter des requêtes.")
    else:
        st.markdown("Requêtes rapides")
        colA, colB, colC = st.columns(3)
        if colA.button("Créer index sur nom_voie"):
            try:
                create_index_if_not_exists(conn, "CREATE INDEX IF NOT EXISTS idx_adresse_nom_voie ON referentiels.adresse_postale (nom_voie);")
                st.success("Index sur nom_voie en place")
            except Exception as e:
                st.error(str(e))
        if colB.button("Créer index sur (lat, lon)"):
            try:
                create_index_if_not_exists(conn, "CREATE INDEX IF NOT EXISTS idx_adresse_lat_lon ON referentiels.adresse_postale (lat, lon);")
                st.success("Index sur (lat, lon) en place")
            except Exception as e:
                st.error(str(e))
        if colC.button("Supprimer index (demo)"):
            try:
                with conn.cursor() as cur:
                    cur.execute("DROP INDEX IF EXISTS idx_adresse_nom_voie;")
                    cur.execute("DROP INDEX IF EXISTS idx_adresse_lat_lon;")
                st.warning("Index supprimés (demo)")
            except Exception as e:
                st.error(str(e))

        # Benchmarks: avant/après index - tableau et graphiques
        st.markdown("Benchmark: 'rue des jacinthes' et coordonnées exactes")
        q1 = "SELECT nom_commune, code_post FROM referentiels.adresse_postale WHERE nom_voie = 'rue des jacinthes';"
        q2 = "SELECT numero, nom_voie, nom_commune FROM referentiels.adresse_postale WHERE lat=49.100550230878 AND lon=6.18587523388308;"
        col1, col2 = st.columns(2)
        if col1.button("Mesurer sans index (les deux requêtes)"):
            try:
                d1 = measure_query_time(conn, q1)
                d2 = measure_query_time(conn, q2)
                st.session_state.bench = {"sans": {"jac": d1*1000, "coord": d2*1000}}
                st.success("Mesure sans index effectuée")
            except Exception as e:
                st.error(str(e))
        if col2.button("Créer index et remesurer"):
            try:
                create_index_if_not_exists(conn, "CREATE INDEX IF NOT EXISTS idx_adresse_nom_voie ON referentiels.adresse_postale (nom_voie);")
                create_index_if_not_exists(conn, "CREATE INDEX IF NOT EXISTS idx_adresse_lat_lon ON referentiels.adresse_postale (lat, lon);")
                d1 = measure_query_time(conn, q1)
                d2 = measure_query_time(conn, q2)
                base = st.session_state.get("bench", {})
                base["avec"] = {"jac": d1*1000, "coord": d2*1000}
                st.session_state.bench = base
                st.success("Mesure avec index effectuée")
            except Exception as e:
                st.error(str(e))

        bench = st.session_state.get("bench")
        if bench:
            st.markdown("Résultats benchmark (ms)")
            rows = []
            for cas in ["sans", "avec"]:
                if cas in bench:
                    rows.append({"cas": cas, "rue des jacinthes": bench[cas]["jac"], "coord (lat,lon)": bench[cas]["coord"]})
            dfb = pd.DataFrame(rows).set_index("cas")
            st.dataframe(dfb)
            st.bar_chart(dfb)
            try:
                import plotly.express as px
                dfm = dfb.reset_index().melt(id_vars="cas", var_name="requete", value_name="ms")
                fig = px.bar(dfm, x="requete", y="ms", color="cas", barmode="group", title="Comparatif avant/après index")
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                pass

        st.markdown("Zone SQL libre")
        sql_text = st.text_area("SQL", value="SELECT now();", height=200)
        if st.button("Exécuter"):
            try:
                df = query_df(conn, sql_text)
                st.dataframe(df)
                low = sql_text.lower()
                if "explain" in low:
                    st.info("EXPLAIN affiché. Pour des chiffres de coût, utilisez 'EXPLAIN' puis lisez la première ligne.")
            except Exception as e:
                st.error(str(e))

with Tab3:
    st.subheader("Charge (pgbench)")
    if shutil.which("pgbench") is None:
        st.info("pgbench n'est pas disponible sur ce système. Utilisez le script bash pour l'installer et l'initialiser.")
    else:
        params = st.session_state.conn_params
        host = params.get("host", "127.0.0.1") or "127.0.0.1"
        port = int(params.get("port", 5432))
        dbname = params.get("dbname", "postgres")
        user = params.get("user", "postgres")
        env = dict(PGPASSWORD=params.get("password", ""))

        # Exécution simple
        st.markdown("Exécution simple")
        col1, col2, col3 = st.columns(3)
        scale = col1.number_input("Scale (-s)", value=10, min_value=1, step=1)
        clients = col2.number_input("Clients (-c)", value=20, min_value=1, step=1)
        duration = col3.number_input("Durée (-T, s)", value=30, min_value=1, step=1)
        init_needed = st.checkbox("Initialiser (-i)", value=False)

        if st.button("Lancer pgbench"):
            try:
                if init_needed:
                    init_cmd = ["pgbench", f"-h{host}", f"-p{port}", f"-U{user}", "-i", f"-s{scale}", dbname]
                    st.write("Initialisation: " + " ".join(init_cmd))
                    res = subprocess.run(init_cmd, capture_output=True, text=True, env=env, timeout=600)
                    st.code(res.stdout + "\n" + res.stderr)
                    if res.returncode != 0:
                        st.error("Initialisation pgbench échouée")
                        st.stop()
                run_cmd = ["pgbench", f"-h{host}", f"-p{port}", f"-U{user}", f"-c{clients}", f"-T{duration}", dbname]
                st.write("Exécution: " + " ".join(run_cmd))
                res = subprocess.run(run_cmd, capture_output=True, text=True, env=env, timeout=max(60, duration+30))
                st.code(res.stdout + "\n" + res.stderr)
                out = res.stdout + "\n" + res.stderr
                met = parse_pgbench_output(out)
                if "pgbench_runs" not in st.session_state:
                    st.session_state.pgbench_runs = []
                st.session_state.pgbench_runs.append({
                    "profil": "simple",
                    "clients": clients,
                    "tps": met.get("tps_excl") or met.get("tps_incl"),
                    "lat": met.get("latency_avg_ms"),
                    "init_ms": met.get("initial_conn_ms"),
                    "processed": met.get("processed"),
                    "failed": met.get("failed"),
                })
            except Exception as e:
                st.error(str(e))

        st.markdown("---")
        st.markdown("Campagne IMPACT SUR LE HARDWARE / TUNING")
        ccol1, ccol2 = st.columns(2)
        profil = ccol1.text_input("Nom du profil (ex: 2GB RAM, tuning A)", value="profil-1")
        clients_series = ccol2.text_input("Série de clients (liste)", value="20,50,75,100,125,150,175,200")
        try:
            clients_list = [int(x.strip()) for x in clients_series.split(',') if x.strip()]
        except Exception:
            clients_list = [20, 50, 75, 100, 125, 150, 175, 200]
        duration2 = st.number_input("Durée par point (-T, s)", value=20, min_value=5, step=5)
        scale2 = st.number_input("Scale d'initialisation (-s)", value=10, min_value=1, step=1)
        do_init = st.checkbox("Initialiser pgbench avant la campagne (-i)", value=False)
        colx, coly, colz = st.columns(3)
        if colx.button("Lancer la campagne"):
            try:
                if do_init:
                    init_cmd = ["pgbench", f"-h{host}", f"-p{port}", f"-U{user}", "-i", f"-s{scale2}", dbname]
                    st.write("Initialisation: " + " ".join(init_cmd))
                    res = subprocess.run(init_cmd, capture_output=True, text=True, env=env, timeout=900)
                    st.code(res.stdout + "\n" + res.stderr)
                    if res.returncode != 0:
                        st.error("Initialisation pgbench échouée")
                        st.stop()
                results = []
                for cval in clients_list:
                    run_cmd = ["pgbench", f"-h{host}", f"-p{port}", f"-U{user}", f"-c{cval}", f"-T{duration2}", dbname]
                    st.write("Exécution: " + " ".join(run_cmd))
                    res = subprocess.run(run_cmd, capture_output=True, text=True, env=env, timeout=max(60, duration2+30))
                    out = res.stdout + "\n" + res.stderr
                    st.code(out)
                    tps = None
                    lat = None
                    for line in out.splitlines():
                        if "including connections establishing" in line and "tps" in line:
                            try:
                                tps = float(line.split("=")[-1].split()[0])
                            except Exception:
                                pass
                        if "latency average" in line:
                            try:
                                lat = float(line.split("=")[-1].split()[0])
                            except Exception:
                                pass
                    results.append({"profil": profil, "clients": cval, "tps": tps, "lat": lat})
                if "pgbench_campaigns" not in st.session_state:
                    st.session_state.pgbench_campaigns = []
                st.session_state.pgbench_campaigns.extend(results)
                st.success("Campagne terminée")
            except Exception as e:
                st.error(str(e))
        if coly.button("Vider résultats"):
            st.session_state.pop("pgbench_campaigns", None)
            st.session_state.pop("pgbench_runs", None)
            st.info("Résultats supprimés")
        if colz.button("Exporter CSV"):
            import csv
            rows = st.session_state.get("pgbench_campaigns", [])
            dfexp = pd.DataFrame(rows)
            csv_buf = io.StringIO()
            dfexp.to_csv(csv_buf, index=False)
            st.download_button("Télécharger pgbench.csv", data=csv_buf.getvalue(), file_name="pgbench.csv", mime="text/csv")

        # Visualisations IMPACT SUR LE HARDWARE / TUNING
        rows = st.session_state.get("pgbench_campaigns", [])
        if rows:
            dfr = pd.DataFrame(rows)
            st.markdown("Tableau des résultats")
            st.dataframe(dfr)

            # TPS vs clients par profil
            st.markdown("IMPACT SUR LE HARDWARE - TPS")
            try:
                pivot_tps = dfr.pivot_table(index="clients", columns="profil", values="tps", aggfunc="mean").sort_index()
                st.line_chart(pivot_tps)
            except Exception:
                pass
            # Latence vs clients par profil
            st.markdown("IMPACT SUR LE HARDWARE - Latence moyenne (ms)")
            try:
                pivot_lat = dfr.pivot_table(index="clients", columns="profil", values="lat", aggfunc="mean").sort_index()
                st.area_chart(pivot_lat)
            except Exception:
                pass

            # Comparatif tuning par profil (barres groupées sur le max des clients en commun)
            st.markdown("TUNING PERFORMANCE - Comparatif par profil")
            try:
                import plotly.express as px
                # normaliser: moyenne de tps sur toute la campagne
                agg = dfr.groupby("profil").agg(tps_moy=("tps","mean"), lat_moy=("lat","mean")).reset_index()
                fig1 = px.bar(agg, x="profil", y="tps_moy", title="TPS moyen par profil")
                st.plotly_chart(fig1, use_container_width=True)
                fig2 = px.bar(agg, x="profil", y="lat_moy", title="Latence moyenne (ms) par profil")
                st.plotly_chart(fig2, use_container_width=True)
            except Exception:
                pass

with Tab4:
    st.subheader("Monitoring")
    if not conn:
        st.info("Connectez-vous pour voir le monitoring.")
    else:
        try:
            df_idx = query_df(conn, "SELECT * FROM v_index_usage ORDER BY relname, indexrelname LIMIT 1000;")
            st.markdown("v_index_usage")
            if df_idx.empty:
                st.info("v_index_usage vide ou non définie.")
            else:
                st.dataframe(df_idx)
        except Exception as e:
            st.warning("v_index_usage non disponible: " + str(e))
        try:
            df_tbl = query_df(conn, "SELECT * FROM v_table_stats ORDER BY relname LIMIT 1000;")
            st.markdown("v_table_stats")
            if df_tbl.empty:
                st.info("v_table_stats vide ou non définie.")
            else:
                st.dataframe(df_tbl)
        except Exception as e:
            st.warning("v_table_stats non disponible: " + str(e))

with Tab5:
    st.subheader("Aide")
    st.markdown(
        """
        Objectif:
        - Apprendre la restauration d'une sauvegarde d'un cluster PostgreSQL
        - Manipuler des tables de forte volumétrie
        - Optimiser le paramétrage mémoire de PostgreSQL
        - Créer des index pour diminuer les temps de traitements

        Sommaire:
        - Installer un cluster de données PostgreSQL
        - Restaurer la sauvegarde fournie
        - Déterminer des index probants
        - Étudier l'impact du dimensionnement Hardware
        - Réaliser un test de charge (pgbench)
        - Étudier l'impact du tuning sur les performances
        """
    )
