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
    render_epic_panel,
    render_assignee_panel,
    render_priority_panel,
    render_age_panel,
)
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

@st.cache_data(ttl=30 * 60)
def cached_search_issues(
    domain,
    email,
    token,
    jql_query,
    epic_link_field_id,
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
    ]

    if epic_link_field_id:
        fields.append(epic_link_field_id)

    return client.search_issues_jql(jql_query, fields)

if refresh:
    st.cache_data.clear()
    st.session_state["resolution_time_loaded"] = False

    if "resolution_time_df" in st.session_state:
        del st.session_state["resolution_time_df"]

    if "resolution_time_signature" in st.session_state:
        del st.session_state["resolution_time_signature"]

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

def add_estimates_to_issue_dataframe(
    issue_df: pd.DataFrame,
    issues: list[dict],
) -> pd.DataFrame:
    if issue_df.empty:
        return issue_df

    estimate_map = {}

    for issue in issues:
        issue_key = issue.get("key", "")
        fields = issue.get("fields") or {}

        estimate_map[issue_key] = estimate_hours_from_fields(fields)

    updated_df = issue_df.copy()

    updated_df["StimaOre"] = (
        updated_df["Issue"]
        .map(estimate_map)
        .fillna(0)
        .astype(float)
    )

    updated_df["Stima (in ore)"] = updated_df["StimaOre"]

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

    with st.spinner("Caricamento issue Jira..."):
        issues = cached_search_issues(
            jira_domain,
            jira_email,
            jira_api_token,
            default_jql,
            epic_link_field_id,
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

df = add_estimates_to_issue_dataframe(df, issues)
df = add_issue_urls(df, jira_domain)

if df.empty:
    st.info("Nessun dato disponibile.")
    st.stop()

# ======================
# FILTRI
# ======================

st.sidebar.header("Filtri dashboard")

only_open = st.sidebar.checkbox(
    "Mostra solo task aperti",
    value=False,
    key="filter_only_open",
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
    .replace("", "Nessuna priorità")
    .unique()
)

selected_priorities_ui = st.sidebar.multiselect(
    "Priorità",
    options=priority_options,
    default=[],
    key="filter_priorities",
)

selected_priorities = [
    "" if priority == "Nessuna priorità" else priority
    for priority in selected_priorities_ui
]

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

epic_df = df.copy()
epic_df["EpicFilter"] = epic_df["EpicName"]

epic_df.loc[
    epic_df["EpicFilter"].fillna("").str.strip() == "",
    "EpicFilter",
] = epic_df["EpicKey"]

epic_df.loc[
    epic_df["EpicFilter"].fillna("").str.strip() == "",
    "EpicFilter",
] = "Senza Epic"

epic_options = sorted(epic_df["EpicFilter"].dropna().unique())

selected_epics_ui = st.sidebar.multiselect(
    "Epic",
    options=epic_options,
    default=[],
    key="filter_epics",
)

selected_epics = [
    "" if epic == "Senza Epic" else epic
    for epic in selected_epics_ui
]

df_view = apply_filters(
    df,
    statuses=selected_statuses,
    issue_types=selected_issue_types,
    assignees=selected_assignees,
    priorities=selected_priorities,
    epics=selected_epics,
    only_open=only_open,
)

# ======================
# DASHBOARD
# ======================

st.divider()

render_kpis(df_view)

st.divider()

tab_overview, tab_epic, tab_people, tab_resolution_time = st.tabs(
    [
        "Overview",
        "Epic",
        "Persone",
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

    st.divider()

    render_age_panel(df_view, key_suffix="overview")

with tab_epic:
    render_epic_panel(df_view, key_suffix="epic")

with tab_people:
    render_assignee_panel(df_view, key_suffix="people")

with tab_resolution_time:
    render_resolution_time_section(
        issue_df=df_view,
        jira_domain=jira_domain,
        jira_email=jira_email,
        jira_api_token=jira_api_token,
    )
