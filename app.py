import io
import requests
import streamlit as st
import pandas as pd

from datetime import date, timedelta, datetime
from requests.auth import HTTPBasicAuth

from auth import login_required, render_logout
from jira_client import JiraClient
from data_processing import (
    build_issues_dataframe,
    add_issue_urls,
    apply_filters,
    create_excel_export,
)
from ui_components import (
    render_kpis,
    render_status_panel,
    render_status_category_panel,
    render_epic_panel,
    render_assignee_panel,
    render_priority_panel,
    render_age_panel,
    render_detail_table,
    render_worklog_tables,
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

st.sidebar.header("Periodo worklog")

worklog_date_from = st.sidebar.date_input(
    "Dal",
    value=date.today() - timedelta(days=7),
    key="worklog_date_from",
)

worklog_date_to = st.sidebar.date_input(
    "Al",
    value=date.today(),
    key="worklog_date_to",
)

if worklog_date_from > worklog_date_to:
    st.sidebar.error("Periodo worklog non valido.")
    st.stop()

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

def get_issue_worklogs(domain, email, token, issue_key):
    domain = normalize_domain(domain)
    base_url = f"https://{domain}/rest/api/3"

    auth = HTTPBasicAuth(email, token)

    headers = {
        "Accept": "application/json",
    }

    start_at = 0
    max_results = 100
    all_worklogs = []

    while True:
        url = f"{base_url}/issue/{issue_key}/worklog"

        params = {
            "startAt": start_at,
            "maxResults": max_results,
        }

        response = requests.get(
            url,
            params=params,
            headers=headers,
            auth=auth,
            timeout=60,
        )

        if not response.ok:
            raise RuntimeError(
                f"Errore Jira worklog {issue_key}: "
                f"{response.status_code} - {response.text}"
            )

        data = response.json()
        worklogs = data.get("worklogs", [])

        all_worklogs.extend(worklogs)

        total = data.get("total", 0)
        start_at += len(worklogs)

        if start_at >= total:
            break

        if not worklogs:
            break

    return all_worklogs

if refresh:
    st.cache_data.clear()
    st.session_state["worklog_loaded"] = False
    st.session_state["resolution_time_loaded"] = False

    if "worklog_df" in st.session_state:
        del st.session_state["worklog_df"]

    if "resolution_time_df" in st.session_state:
        del st.session_state["resolution_time_df"]

    if "resolution_time_signature" in st.session_state:
        del st.session_state["resolution_time_signature"]

    st.rerun()

# ======================
# WORKLOG HELPERS
# ======================

def parse_worklog_date(started_value):
    if not started_value:
        return None

    try:
        return datetime.strptime(started_value[:10], "%Y-%m-%d").date()
    except Exception:
        return None

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

def build_worklog_dataframe(
    issue_df: pd.DataFrame,
    worklogs_by_issue: dict,
    date_from: date,
    date_to: date,
):
    columns = [
        "Data",
        "Utente",
        "Issue",
        "Summary",
        "EpicKey",
        "EpicName",
        "StimaOre",
        "Ore",
        "Ore Consuntivate",
        "Stato",
        "Stima (in ore)",
        "Url",
    ]

    if issue_df.empty:
        return pd.DataFrame(columns=columns)

    issue_lookup = (
        issue_df
        .drop_duplicates(subset=["Issue"])
        .set_index("Issue")
        .to_dict(orient="index")
    )

    rows = []

    for issue_key, worklogs in worklogs_by_issue.items():
        issue_info = issue_lookup.get(issue_key, {})
        stima_ore = issue_info.get("StimaOre", 0)

        for worklog in worklogs:
            worklog_day = parse_worklog_date(worklog.get("started"))

            if worklog_day is None:
                continue

            if worklog_day < date_from or worklog_day > date_to:
                continue

            author = worklog.get("author") or {}

            user = (
                author.get("displayName")
                or author.get("emailAddress")
                or author.get("accountId")
                or ""
            )

            hours = round((worklog.get("timeSpentSeconds", 0) or 0) / 3600, 2)

            rows.append(
                {
                    "Data": worklog_day,
                    "Utente": user,
                    "Issue": issue_key,
                    "Summary": issue_info.get("Summary", ""),
                    "EpicKey": issue_info.get("EpicKey", ""),
                    "EpicName": issue_info.get("EpicName", ""),
                    "StimaOre": stima_ore,
                    "Ore": hours,
                    "Ore Consuntivate": hours,
                    "Stato": issue_info.get("Stato", ""),
                    "Stima (in ore)": stima_ore,
                    "Url": issue_info.get("Url", ""),
                }
            )

    df = pd.DataFrame(rows, columns=columns)

    if df.empty:
        return df

    df["Data"] = pd.to_datetime(df["Data"])
    df["StimaOre"] = pd.to_numeric(df["StimaOre"], errors="coerce").fillna(0)
    df["Ore"] = pd.to_numeric(df["Ore"], errors="coerce").fillna(0)

    df["Ore Consuntivate"] = pd.to_numeric(
        df["Ore Consuntivate"],
        errors="coerce",
    ).fillna(0)

    df["Stima (in ore)"] = pd.to_numeric(
        df["Stima (in ore)"],
        errors="coerce",
    ).fillna(0)

    df = df.sort_values(
        ["Data", "Utente", "Issue"],
        ascending=[False, True, True],
    )

    return df

def create_worklog_excel_export(worklog_df: pd.DataFrame):
    output = io.BytesIO()

    export_df = worklog_df.copy()

    if "Data" in export_df.columns:
        export_df["Data"] = pd.to_datetime(export_df["Data"], errors="coerce")

    export_columns = [
        "Data",
        "Utente",
        "Issue",
        "Summary",
        "EpicKey",
        "EpicName",
        "StimaOre",
        "Ore Consuntivate",
        "Stato",
        "Stima (in ore)",
        "Url",
    ]

    existing_columns = [
        column
        for column in export_columns
        if column in export_df.columns
    ]

    export_df = export_df[existing_columns]

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Worklog")

        workbook = writer.book
        worksheet = writer.sheets["Worklog"]

        date_format = workbook.add_format({"num_format": "dd/mm/yyyy"})
        number_format = workbook.add_format({"num_format": "0.00"})

        worksheet.set_column("A:A", 12, date_format)
        worksheet.set_column("B:B", 28)
        worksheet.set_column("C:C", 14)
        worksheet.set_column("D:D", 60)
        worksheet.set_column("E:F", 28)
        worksheet.set_column("G:H", 16, number_format)
        worksheet.set_column("I:I", 18)
        worksheet.set_column("J:J", 16, number_format)
        worksheet.set_column("K:K", 60)

    output.seek(0)

    return output

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

tab_overview, tab_epic, tab_people, tab_worklog, tab_resolution_time, tab_details = st.tabs(
    [
        "Overview",
        "Epic",
        "Persone",
        "Worklog",
        "Tempi risoluzione",
        "Dettaglio",
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

with tab_worklog:
    st.subheader("Worklog")

    st.caption(
        "Le tabelle mostrano le ore consuntivate su Jira nel periodo selezionato "
        "nella sidebar."
    )

    if df_view.empty:
        st.info("Nessuna issue disponibile per i filtri selezionati.")
    else:
        issue_keys = (
            df_view["Issue"]
            .dropna()
            .drop_duplicates()
            .sort_values()
            .tolist()
        )

        if not issue_keys:
            st.info("Nessuna issue disponibile per il caricamento dei worklog.")
        else:
            load_worklog = st.button(
                "Carica worklog",
                key="load_worklog_button",
                use_container_width=False,
            )

            if load_worklog:
                st.session_state["worklog_loaded"] = True

            if not st.session_state.get("worklog_loaded", False):
                st.info(
                    "Premi **Carica worklog** per recuperare le ore segnate su Jira "
                    "per le issue attualmente filtrate."
                )
            else:
                worklogs_by_issue = {}

                progress_text = st.empty()
                progress_bar = st.progress(0)

                for index, issue_key in enumerate(issue_keys, start=1):
                    progress_text.write(
                        f"Caricamento worklog {index}/{len(issue_keys)}: {issue_key}"
                    )

                    try:
                        worklogs_by_issue[issue_key] = get_issue_worklogs(
                            jira_domain,
                            jira_email,
                            jira_api_token,
                            issue_key,
                        )
                    except Exception:
                        worklogs_by_issue[issue_key] = []

                    progress_bar.progress(index / len(issue_keys))

                progress_text.empty()
                progress_bar.empty()

                worklog_df = build_worklog_dataframe(
                    issue_df=df_view,
                    worklogs_by_issue=worklogs_by_issue,
                    date_from=worklog_date_from,
                    date_to=worklog_date_to,
                )

                render_worklog_tables(
                    worklog_df,
                    date_from=worklog_date_from,
                    date_to=worklog_date_to,
                    key_suffix="worklog",
                )

                if not worklog_df.empty:
                    worklog_excel_file = create_worklog_excel_export(worklog_df)

                    st.download_button(
                        label="📥 Scarica Excel Worklog",
                        data=worklog_excel_file,
                        file_name="jira_worklog.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_excel_worklog",
                    )

with tab_resolution_time:
    render_resolution_time_section(
        issue_df=df_view,
        jira_domain=jira_domain,
        jira_email=jira_email,
        jira_api_token=jira_api_token,
    )

with tab_details:
    render_detail_table(df_view, key_suffix="details")

    excel_file = create_excel_export(df_view)

    st.download_button(
        label="📥 Scarica Excel",
        data=excel_file,
        file_name="jira_project_dashboard.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_excel_details",
    )
