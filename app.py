import streamlit as st
import pandas as pd

from auth import login_required, render_logout
from jira_client import JiraClient
from data_processing import (
    build_issues_dataframe,
    add_issue_urls,
    apply_filters,
)
from ui_components import (
    render_kpis,
    render_status_panel,
    render_status_category_panel,
    render_assignee_panel,
    render_priority_panel,
    render_priority_monthly_panel,
    render_estimate_compliance_panel,
)
from pickup_time import render_pickup_time_section
from resolution_time import render_resolution_time_section

# ======================
# STREAMLIT CONFIG
# ======================

st.set_page_config(
    page_title="Jira Project Dashboard",
    page_icon="📊",
    layout="wide",
)

# ======================
# LOGIN
# ======================

login_required()

# ======================
# PAGE HEADER
# ======================

st.title("📊 Jira Project Dashboard")
st.caption("Dashboard di monitoraggio avanzamento progetto basata su issue Jira")

# ======================
# CONFIG
# ======================

CUSTOMER_PRIORITY_FIELD_ALIASES = {
    "priorità cliente",
    "priorita cliente",
    "priorità cliente ",
    "priorita cliente ",
    "priorità del cliente",
    "priorita del cliente",
}

ALLOWED_EPIC_NAMES = {
    "AM",
    "GESTIONE MEMORIA",
}

def get_secret(section: str, key: str, default=None):
    try:
        return st.secrets[section][key]
    except Exception:
        return default

def normalize_domain(domain: str) -> str:
    domain = str(domain).strip()
    domain = domain.replace("https://", "")
    domain = domain.replace("http://", "")
    domain = domain.strip("/")
    return domain

def normalize_field_name(value) -> str:
    if value is None:
        return ""

    return str(value).strip().lower()

def normalize_text(value) -> str:
    if value is None:
        return ""

    return str(value).strip().upper()

def is_allowed_epic_value(value) -> bool:
    normalized_value = normalize_text(value)

    if not normalized_value:
        return False

    if normalized_value in ALLOWED_EPIC_NAMES:
        return True

    for allowed_epic_name in ALLOWED_EPIC_NAMES:
        if allowed_epic_name in normalized_value:
            return True

    return False

def filter_allowed_epics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    filtered_df = df.copy()

    if "EpicName" not in filtered_df.columns:
        filtered_df["EpicName"] = ""

    if "EpicKey" not in filtered_df.columns:
        filtered_df["EpicKey"] = ""

    filtered_df = filtered_df[
        filtered_df["EpicName"].apply(is_allowed_epic_value)
        | filtered_df["EpicKey"].apply(is_allowed_epic_value)
    ].copy()

    return filtered_df

jira_domain = get_secret("JIRA", "DOMAIN")
jira_email = get_secret("JIRA", "EMAIL")
jira_api_token = get_secret("JIRA", "API_TOKEN")
default_jql = get_secret(
    "JIRA",
    "DEFAULT_JQL",
    "project is not EMPTY ORDER BY updated DESC",
)

if not jira_domain or not jira_email or not jira_api_token:
    st.error(
        """
        Configurazione Jira mancante.

        Imposta i seguenti valori nei secrets di Streamlit:

        ```toml
        [JIRA]
        DOMAIN = "your-domain.atlassian.net"
        EMAIL = "your.email@reply.it"
        API_TOKEN = "your-api-token"
        DEFAULT_JQL = "project = KAN ORDER BY updated DESC"
        ```
        """
    )
    st.stop()

jira_domain = normalize_domain(jira_domain)

# ======================
# SIDEBAR
# ======================

render_logout()

st.sidebar.header("Azioni")

refresh = st.sidebar.button(
    "Aggiorna dati",
    key="refresh_data",
)

# ======================
# CACHE
# ======================

@st.cache_data(ttl=24 * 60 * 60)
def cached_detect_epic_link_field(domain, email, token):
    client = JiraClient(domain, email, token)
    return client.detect_epic_link_field()

@st.cache_data(ttl=24 * 60 * 60)
def cached_detect_customer_priority_field(domain, email, token):
    client = JiraClient(domain, email, token)

    try:
        fields = client.get_fields()
    except Exception:
        return None

    for field in fields:
        field_name = normalize_field_name(field.get("name"))

        if field_name in CUSTOMER_PRIORITY_FIELD_ALIASES:
            return field.get("id")

    return None

@st.cache_data(ttl=30 * 60)
def cached_search_issues(
    domain,
    email,
    token,
    jql_query,
    epic_link_field_id,
    customer_priority_field_id,
):
    client = JiraClient(domain, email, token)

    fields = [
        "summary",
        "issuetype",
        "status",
        "assignee",
        "reporter",
        "priority",
        "parent",
        "created",
        "updated",
        "duedate",
        "resolutiondate",
        "timetracking",
        "timeoriginalestimate",
        "timespent",
        "aggregatetimespent",
    ]

    if epic_link_field_id:
        fields.append(epic_link_field_id)

    if customer_priority_field_id:
        fields.append(customer_priority_field_id)

    return client.search_issues_jql(jql_query, fields)

if refresh:
    st.cache_data.clear()
    st.session_state["resolution_time_loaded"] = False
    st.session_state["pickup_time_loaded"] = False

    if "resolution_time_df" in st.session_state:
        del st.session_state["resolution_time_df"]

    if "resolution_time_signature" in st.session_state:
        del st.session_state["resolution_time_signature"]

    if "pickup_time_df" in st.session_state:
        del st.session_state["pickup_time_df"]

    if "pickup_time_signature" in st.session_state:
        del st.session_state["pickup_time_signature"]

    st.rerun()

# ======================
# ISSUE HELPERS
# ======================

def estimate_hours_from_fields(fields: dict) -> float:
    timetracking = fields.get("timetracking") or {}

    seconds = timetracking.get("originalEstimateSeconds")

    if seconds is None:
        seconds = fields.get("timeoriginalestimate")

    return round((seconds or 0) / 3600, 2)

def spent_hours_from_fields(fields: dict) -> float:
    timetracking = fields.get("timetracking") or {}

    seconds = timetracking.get("timeSpentSeconds")

    if seconds is None:
        seconds = fields.get("timespent")

    if seconds is None:
        seconds = fields.get("aggregatetimespent")

    return round((seconds or 0) / 3600, 2)

def add_time_tracking_to_issue_dataframe(
    issue_df: pd.DataFrame,
    issues: list[dict],
) -> pd.DataFrame:
    if issue_df.empty:
        return issue_df

    estimate_map = {}
    spent_map = {}

    for issue in issues:
        issue_key = issue.get("key", "")
        fields = issue.get("fields") or {}

        estimate_map[issue_key] = estimate_hours_from_fields(fields)
        spent_map[issue_key] = spent_hours_from_fields(fields)

    updated_df = issue_df.copy()

    updated_df["StimaOre"] = (
        updated_df["Issue"]
        .map(estimate_map)
        .fillna(0)
        .astype(float)
    )

    updated_df["TempoImpiegatoOre"] = (
        updated_df["Issue"]
        .map(spent_map)
        .fillna(0)
        .astype(float)
    )

    updated_df["Stima (in ore)"] = updated_df["StimaOre"]
    updated_df["Tempo impiegato (in ore)"] = updated_df["TempoImpiegatoOre"]

    return updated_df

def extract_custom_field_display_value(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, dict):
        for key in ["value", "name", "displayName", "label"]:
            if key in value and value.get(key):
                return str(value.get(key)).strip()

        return str(value)

    if isinstance(value, list):
        values = [
            extract_custom_field_display_value(item)
            for item in value
        ]

        values = [
            item
            for item in values
            if item
        ]

        return ", ".join(values)

    return str(value).strip()

def add_customer_priority_to_issue_dataframe(
    issue_df: pd.DataFrame,
    issues: list[dict],
    customer_priority_field_id: str | None,
) -> pd.DataFrame:
    if issue_df.empty:
        return issue_df

    updated_df = issue_df.copy()

    if not customer_priority_field_id:
        updated_df["Priorità cliente"] = ""
        updated_df["Priority"] = ""
        return updated_df

    customer_priority_map = {}

    for issue in issues:
        issue_key = issue.get("key", "")
        fields = issue.get("fields") or {}

        raw_value = fields.get(customer_priority_field_id)
        customer_priority_map[issue_key] = extract_custom_field_display_value(raw_value)

    updated_df["Priorità cliente"] = (
        updated_df["Issue"]
        .map(customer_priority_map)
        .fillna("")
    )

    updated_df["Priority"] = updated_df["Priorità cliente"]

    return updated_df

# ======================
# LOAD DATA
# ======================

try:
    with st.spinner("Rilevamento campi Jira..."):
        epic_link_field_id = cached_detect_epic_link_field(
            jira_domain,
            jira_email,
            jira_api_token,
        )

        customer_priority_field_id = cached_detect_customer_priority_field(
            jira_domain,
            jira_email,
            jira_api_token,
        )

    with st.spinner("Caricamento issue Jira..."):
        issues = cached_search_issues(
            jira_domain,
            jira_email,
            jira_api_token,
            default_jql,
            epic_link_field_id,
            customer_priority_field_id,
        )

except Exception as exc:
    st.error("Errore durante il caricamento dati da Jira.")
    st.exception(exc)
    st.stop()

# ======================
# EMPTY STATE
# ======================

if not issues:
    st.info("Nessuna issue trovata per il JQL configurato nei secrets.")
    st.stop()

df = build_issues_dataframe(
    issues,
    epic_link_field_id=epic_link_field_id,
    sprint_field_id=None,
)

df = add_time_tracking_to_issue_dataframe(df, issues)

df = add_customer_priority_to_issue_dataframe(
    issue_df=df,
    issues=issues,
    customer_priority_field_id=customer_priority_field_id,
)

df = add_issue_urls(df, jira_domain)

# ======================
# FILTRO GLOBALE EPIC
# ======================

df = filter_allowed_epics(df)

if df.empty:
    st.info(
        "Nessun ticket disponibile nelle Epic abilitate: "
        "**AM** e **Gestione Memoria**."
    )
    st.stop()

if not customer_priority_field_id:
    st.warning(
        "Campo custom **Priorità cliente** non trovato su Jira. "
        "Il filtro e il grafico priorità potrebbero non usare il campo corretto. "
        "Verifica il nome esatto del campo custom in Jira."
    )

# ======================
# FILTRI
# ======================

st.sidebar.header("Filtri dashboard")

st.sidebar.caption(
    "La dashboard considera solo i ticket appartenenti alle Epic "
    "**AM** e **Gestione Memoria**."
)

status_options = sorted(df["Stato"].dropna().unique())

selected_statuses = st.sidebar.multiselect(
    "Stato",
    options=status_options,
    default=[],
    key="filter_statuses",
)

issue_type_options = sorted(df["IssueType"].dropna().unique())

selected_issue_types = st.sidebar.multiselect(
    "Issue Type",
    options=issue_type_options,
    default=[],
    key="filter_issue_types",
)

priority_options = sorted(
    df["Priority"]
    .fillna("")
    .replace("", "Nessuna priorità cliente")
    .unique()
)

selected_priorities_ui = st.sidebar.multiselect(
    "Priorità cliente",
    options=priority_options,
    default=[],
    key="filter_priorities",
)

selected_priorities = [
    "" if priority == "Nessuna priorità cliente" else priority
    for priority in selected_priorities_ui
]

epic_df = df.copy()
epic_df["EpicFilter"] = epic_df["EpicName"]

epic_df.loc[
    epic_df["EpicFilter"].fillna("").str.strip() == "",
    "EpicFilter",
] = epic_df["EpicKey"]

epic_options = sorted(epic_df["EpicFilter"].dropna().unique())

selected_epics = st.sidebar.multiselect(
    "Epic",
    options=epic_options,
    default=[],
    key="filter_epics",
)

assignee_options = sorted(
    df["Assignee"]
    .fillna("")
    .replace("", "Non assegnato")
    .unique()
)

selected_assignees_ui = st.sidebar.multiselect(
    "Assegnatario",
    options=assignee_options,
    default=[],
    key="filter_assignees",
)

selected_assignees = [
    "" if assignee == "Non assegnato" else assignee
    for assignee in selected_assignees_ui
]

df_view = apply_filters(
    df,
    statuses=selected_statuses,
    issue_types=selected_issue_types,
    assignees=selected_assignees,
    priorities=selected_priorities,
    epics=selected_epics,
)

# ======================
# DASHBOARD
# ======================

st.divider()

render_kpis(df_view)

st.divider()

(
    tab_overview,
    tab_people,
    tab_priority_trend,
    tab_estimates,
    tab_pickup_time,
    tab_resolution_time,
) = st.tabs(
    [
        "Overview",
        "Persone",
        "Andamento priorità",
        "Rispetto stime",
        "Presa in carico",
        "Tempi risoluzione",
    ]
)

with tab_overview:
    render_status_panel(df_view, key_suffix="overview")

    st.divider()

    col1, col2 = st.columns([1, 1])

    with col1:
        render_status_category_panel(df_view, key_suffix="overview")

    with col2:
        render_priority_panel(df_view, key_suffix="overview")

with tab_people:
    render_assignee_panel(df_view, key_suffix="people")

with tab_priority_trend:
    render_priority_monthly_panel(df_view, key_suffix="priority_trend")

with tab_estimates:
    render_estimate_compliance_panel(df_view, key_suffix="estimates")

with tab_pickup_time:
    render_pickup_time_section(
        issue_df=df_view,
        jira_domain=jira_domain,
        jira_email=jira_email,
        jira_api_token=jira_api_token,
    )

with tab_resolution_time:
    render_resolution_time_section(
        issue_df=df_view,
        jira_domain=jira_domain,
        jira_email=jira_email,
        jira_api_token=jira_api_token,
    )
