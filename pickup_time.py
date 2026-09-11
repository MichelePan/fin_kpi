import html
import re
import unicodedata
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from requests.auth import HTTPBasicAuth

# ======================
# CONFIG
# ======================

TASK_BUG_TYPES = {
    "task",
    "bug",
}

PICKUP_STATUSES = {
    "ANALISI",
    "ANALISI PRELIMINARE",
    "IN CORSO",
    "IN REVISIONE/TEST",
    "ON HOLD TEMP",
    "BLOCCATO",
}

PRIORITY_ORDER = [
    "Altissima",
    "Alta",
    "Media",
    "Bassa",
    "Fase 2",
]

NO_PRIORITY_LABEL = "Nessuna priorità cliente"

WORKING_TIMEZONE = "Europe/Rome"
WORKING_HOURS_PER_DAY = 8
WORKING_DAY_START_HOUR = 9
LUNCH_BREAK_START_HOUR = 13
LUNCH_BREAK_END_HOUR = 14
WORKING_DAY_END_HOUR = 18

CALCULATED_ESITI = {
    "Calcolato",
}

# ======================
# UI HELPERS
# ======================

def render_metric_card(label, value, color="#172033", background="#ffffff"):
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))

    st.markdown(
        f"""
        <div style="
            background: {background};
            border: 1px solid rgba(16, 24, 40, 0.08);
            border-radius: 16px;
            padding: 18px 18px;
            box-shadow: 0 6px 18px rgba(16, 24, 40, 0.06);
            min-height: 104px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        ">
            <div style="
                color: #667085;
                font-size: 0.88rem;
                font-weight: 600;
                margin-bottom: 8px;
                line-height: 1.2;
            ">
                {safe_label}
            </div>
            <div style="
                color: {color};
                font-size: 2rem;
                font-weight: 800;
                line-height: 1.1;
            ">
                {safe_value}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ======================
# NORMALIZZAZIONE
# ======================

def normalize_domain(domain: str) -> str:
    domain = str(domain).strip()
    domain = domain.replace("https://", "")
    domain = domain.replace("http://", "")
    domain = domain.strip("/")
    return domain

def normalize_text(value) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = text.upper()
    text = re.sub(r"\s+", " ", text)

    return text.strip()

def normalize_issue_type(value) -> str:
    if value is None:
        return ""

    return str(value).strip().lower()

def normalize_status(value) -> str:
    return normalize_text(value)

def normalize_priority(value) -> str:
    if value is None:
        return ""

    return str(value).strip()

def normalize_priority_for_match(value) -> str:
    return normalize_priority(value).lower()

def filter_task_bug(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "IssueType" not in df.columns:
        return df.copy()

    return df[
        df["IssueType"]
        .apply(normalize_issue_type)
        .isin(TASK_BUG_TYPES)
    ].copy()

def get_priority_label(issue_info: dict) -> str:
    priority = issue_info.get("Priority", "")

    if priority is None or str(priority).strip() == "":
        priority = issue_info.get("Priorità cliente", "")

    if priority is None or str(priority).strip() == "":
        return NO_PRIORITY_LABEL

    return str(priority).strip()

# ======================
# TEMPO LAVORATIVO
# ======================

def seconds_to_hours(seconds: float) -> float:
    return round(seconds / 3600, 2)

def hours_to_working_days(hours: float) -> float:
    return round(hours / WORKING_HOURS_PER_DAY, 3)

def to_working_timezone(timestamp):
    if timestamp is None or pd.isna(timestamp):
        return pd.NaT

    parsed = pd.to_datetime(
        timestamp,
        utc=True,
        errors="coerce",
    )

    if pd.isna(parsed):
        return pd.NaT

    return parsed.tz_convert(WORKING_TIMEZONE)

def is_working_day(timestamp: pd.Timestamp) -> bool:
    return timestamp.weekday() < 5

def build_working_interval(day: pd.Timestamp, start_hour: int, end_hour: int):
    timezone = ZoneInfo(WORKING_TIMEZONE)

    start = pd.Timestamp(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=start_hour,
        minute=0,
        second=0,
        tz=timezone,
    )

    end = pd.Timestamp(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=end_hour,
        minute=0,
        second=0,
        tz=timezone,
    )

    return start, end

def overlap_seconds(start_a, end_a, start_b, end_b) -> float:
    overlap_start = max(start_a, start_b)
    overlap_end = min(end_a, end_b)

    if overlap_end <= overlap_start:
        return 0.0

    return max((overlap_end - overlap_start).total_seconds(), 0.0)

def calculate_working_seconds_between(start_ts, end_ts) -> float:
    local_start = to_working_timezone(start_ts)
    local_end = to_working_timezone(end_ts)

    if pd.isna(local_start) or pd.isna(local_end):
        return 0.0

    if local_end <= local_start:
        return 0.0

    total_seconds = 0.0

    current_day = local_start.normalize()
    last_day = local_end.normalize()

    while current_day <= last_day:
        if is_working_day(current_day):
            morning_start, morning_end = build_working_interval(
                current_day,
                WORKING_DAY_START_HOUR,
                LUNCH_BREAK_START_HOUR,
            )

            afternoon_start, afternoon_end = build_working_interval(
                current_day,
                LUNCH_BREAK_END_HOUR,
                WORKING_DAY_END_HOUR,
            )

            total_seconds += overlap_seconds(
                local_start,
                local_end,
                morning_start,
                morning_end,
            )

            total_seconds += overlap_seconds(
                local_start,
                local_end,
                afternoon_start,
                afternoon_end,
            )

        current_day = current_day + pd.Timedelta(days=1)

    return total_seconds

# ======================
# JIRA API
# ======================

def parse_jira_timestamp(value):
    if not value:
        return pd.NaT

    return pd.to_datetime(
        value,
        utc=True,
        errors="coerce",
    )

def get_issue_changelog(
    domain: str,
    email: str,
    token: str,
    issue_key: str,
) -> list[dict]:
    domain = normalize_domain(domain)
    base_url = f"https://{domain}/rest/api/3"

    auth = HTTPBasicAuth(email, token)

    headers = {
        "Accept": "application/json",
    }

    start_at = 0
    max_results = 100
    all_histories = []

    while True:
        url = f"{base_url}/issue/{issue_key}/changelog"

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
                f"Errore Jira changelog {issue_key}: "
                f"{response.status_code} - {response.text}"
            )

        data = response.json() or {}
        histories = data.get("values", []) or []

        all_histories.extend(histories)

        total = data.get("total", 0)
        start_at += len(histories)

        if start_at >= total:
            break

        if not histories:
            break

    return all_histories

# ======================
# CHANGELOG PARSING
# ======================

def extract_status_events(changelog: list[dict]) -> list[dict]:
    events = []

    for history in changelog:
        created = parse_jira_timestamp(history.get("created"))

        if pd.isna(created):
            continue

        items = history.get("items", []) or []

        for item in items:
            field_name = str(item.get("field", "")).strip().lower()

            if field_name != "status":
                continue

            from_status = item.get("fromString", "") or ""
            to_status = item.get("toString", "") or ""

            events.append(
                {
                    "Timestamp": created,
                    "FromStatus": from_status,
                    "ToStatus": to_status,
                    "FromStatusNormalized": normalize_status(from_status),
                    "ToStatusNormalized": normalize_status(to_status),
                }
            )

    events = sorted(
        events,
        key=lambda item: item["Timestamp"],
    )

    return events

def find_pickup_event(events: list[dict], created_ts):
    valid_events = [
        event
        for event in events
        if event["Timestamp"] >= created_ts
    ]

    for event in valid_events:
        to_status = event.get("ToStatusNormalized", "")

        if to_status in PICKUP_STATUSES:
            return event

    return None

# ======================
# CALCOLO PRESA IN CARICO
# ======================

def compute_pickup_time_for_issue(
    issue_info: dict,
    changelog: list[dict],
) -> dict:
    issue_key = issue_info.get("Issue", "")
    created_ts = parse_jira_timestamp(issue_info.get("Created"))

    result = {
        "Issue": issue_key,
        "Summary": issue_info.get("Summary", ""),
        "Assegnatario": issue_info.get("Assignee", "") or "Non assegnato",
        "Priorità cliente": get_priority_label(issue_info),
        "Data creazione": created_ts,
        "Data presa in carico": pd.NaT,
        "Stato presa in carico": "",
        "Tempo presa in carico ore": None,
        "Tempo presa in carico giorni": None,
        "Esito": "",
        "Url": issue_info.get("Url", ""),
    }

    if pd.isna(created_ts):
        result["Esito"] = "Data creazione non disponibile"
        return result

    events = extract_status_events(changelog)

    if not events:
        result["Esito"] = "Changelog stato non disponibile"
        return result

    pickup_event = find_pickup_event(
        events=events,
        created_ts=created_ts,
    )

    if pickup_event is None:
        result["Esito"] = "Transizione presa in carico non trovata"
        return result

    pickup_ts = pickup_event["Timestamp"]

    working_seconds = calculate_working_seconds_between(
        created_ts,
        pickup_ts,
    )

    working_hours = seconds_to_hours(working_seconds)
    working_days = hours_to_working_days(working_hours)

    result["Data presa in carico"] = pickup_ts
    result["Stato presa in carico"] = pickup_event.get("ToStatus", "")
    result["Tempo presa in carico ore"] = working_hours
    result["Tempo presa in carico giorni"] = working_days
    result["Esito"] = "Calcolato"

    return result

def build_pickup_time_dataframe(
    issue_df: pd.DataFrame,
    jira_domain: str,
    jira_email: str,
    jira_api_token: str,
) -> pd.DataFrame:
    columns = [
        "Issue",
        "Summary",
        "Assegnatario",
        "Priorità cliente",
        "Data creazione",
        "Data presa in carico",
        "Stato presa in carico",
        "Tempo presa in carico ore",
        "Tempo presa in carico giorni",
        "Esito",
        "Url",
    ]

    if issue_df.empty:
        return pd.DataFrame(columns=columns)

    task_bug_df = filter_task_bug(issue_df)

    if task_bug_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    issue_records = task_bug_df.to_dict(orient="records")
    total_issues = len(issue_records)

    progress_text = st.empty()
    progress_bar = st.progress(0)

    for index, issue_info in enumerate(issue_records, start=1):
        issue_key = issue_info.get("Issue", "")

        progress_text.write(
            f"Calcolo presa in carico {index}/{total_issues}: {issue_key}"
        )

        try:
            changelog = get_issue_changelog(
                jira_domain,
                jira_email,
                jira_api_token,
                issue_key,
            )

            row = compute_pickup_time_for_issue(
                issue_info=issue_info,
                changelog=changelog,
            )

        except Exception as exc:
            row = {
                "Issue": issue_key,
                "Summary": issue_info.get("Summary", ""),
                "Assegnatario": issue_info.get("Assignee", "") or "Non assegnato",
                "Priorità cliente": get_priority_label(issue_info),
                "Data creazione": parse_jira_timestamp(issue_info.get("Created")),
                "Data presa in carico": pd.NaT,
                "Stato presa in carico": "",
                "Tempo presa in carico ore": None,
                "Tempo presa in carico giorni": None,
                "Esito": f"Errore recupero changelog: {str(exc)[:180]}",
                "Url": issue_info.get("Url", ""),
            }

        rows.append(row)
        progress_bar.progress(index / total_issues)

    progress_text.empty()
    progress_bar.empty()

    result_df = pd.DataFrame(rows, columns=columns)

    result_df["Data creazione"] = pd.to_datetime(
        result_df["Data creazione"],
        errors="coerce",
    )

    result_df["Data presa in carico"] = pd.to_datetime(
        result_df["Data presa in carico"],
        errors="coerce",
    )

    numeric_columns = [
        "Tempo presa in carico ore",
        "Tempo presa in carico giorni",
    ]

    for column in numeric_columns:
        result_df[column] = pd.to_numeric(
            result_df[column],
            errors="coerce",
        )

    return result_df

# ======================
# AGGREGAZIONI
# ======================

def build_priority_pickup_summary(pickup_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Priorità cliente",
        "Ticket calcolati",
        "Tempo medio presa in carico giorni",
        "Tempo medio presa in carico ore",
        "Tempo mediano presa in carico giorni",
        "Tempo massimo presa in carico giorni",
    ]

    if pickup_df.empty:
        return pd.DataFrame(columns=columns)

    calculated_df = pickup_df[
        pickup_df["Esito"].isin(CALCULATED_ESITI)
    ].copy()

    if calculated_df.empty:
        return pd.DataFrame(columns=columns)

    summary_df = (
        calculated_df
        .groupby("Priorità cliente", dropna=False)
        .agg(
            **{
                "Ticket calcolati": ("Issue", "count"),
                "Tempo medio presa in carico giorni": (
                    "Tempo presa in carico giorni",
                    "mean",
                ),
                "Tempo medio presa in carico ore": (
                    "Tempo presa in carico ore",
                    "mean",
                ),
                "Tempo mediano presa in carico giorni": (
                    "Tempo presa in carico giorni",
                    "median",
                ),
                "Tempo massimo presa in carico giorni": (
                    "Tempo presa in carico giorni",
                    "max",
                ),
            }
        )
        .reset_index()
    )

    numeric_columns = [
        "Tempo medio presa in carico giorni",
        "Tempo medio presa in carico ore",
        "Tempo mediano presa in carico giorni",
        "Tempo massimo presa in carico giorni",
    ]

    for column in numeric_columns:
        summary_df[column] = summary_df[column].round(3)

    summary_df["__order"] = summary_df["Priorità cliente"].apply(
        get_priority_order
    )

    summary_df = (
        summary_df
        .sort_values(["__order", "Priorità cliente"])
        .drop(columns=["__order"])
        .reset_index(drop=True)
    )

    return summary_df[columns]

def get_priority_order(priority) -> int:
    normalized_priority = normalize_priority_for_match(priority)

    for index, priority_value in enumerate(PRIORITY_ORDER):
        if normalized_priority == priority_value.lower():
            return index

    if normalized_priority == NO_PRIORITY_LABEL.lower():
        return 9999

    return 999

def get_average_pickup_days_for_priority(
    summary_df: pd.DataFrame,
    priority: str,
):
    if summary_df.empty:
        return None, 0

    matching_df = summary_df[
        summary_df["Priorità cliente"].apply(normalize_priority_for_match)
        == priority.lower()
    ]

    if matching_df.empty:
        return None, 0

    value = matching_df.iloc[0]["Tempo medio presa in carico giorni"]
    count = int(matching_df.iloc[0]["Ticket calcolati"])

    return value, count

def build_esiti_summary(pickup_df: pd.DataFrame) -> pd.DataFrame:
    if pickup_df.empty:
        return pd.DataFrame(columns=["Esito", "Ticket"])

    return (
        pickup_df
        .groupby("Esito", dropna=False)
        .size()
        .reset_index(name="Ticket")
        .sort_values("Ticket", ascending=False)
    )

# ======================
# DISPLAY HELPERS
# ======================

def format_days_value(value):
    if value is None or pd.isna(value):
        return "N/D"

    return f"{round(float(value), 3)} gg lav."

def format_datetime_for_display(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(
        series,
        utc=True,
        errors="coerce",
    )

    try:
        parsed = parsed.dt.tz_convert(WORKING_TIMEZONE)
    except Exception:
        pass

    return parsed.dt.strftime("%d/%m/%Y %H:%M")

def prepare_pickup_detail_for_display(pickup_df: pd.DataFrame) -> pd.DataFrame:
    display_df = pickup_df.copy()

    if "Data creazione" in display_df.columns:
        display_df["Data creazione"] = format_datetime_for_display(
            display_df["Data creazione"]
        )

    if "Data presa in carico" in display_df.columns:
        display_df["Data presa in carico"] = format_datetime_for_display(
            display_df["Data presa in carico"]
        )

    return display_df

# ======================
# UI
# ======================

def render_pickup_time_section(
    issue_df: pd.DataFrame,
    jira_domain: str,
    jira_email: str,
    jira_api_token: str,
):
    st.subheader("Tempi di presa in carico")

    st.caption(
        "Il tempo di presa in carico viene calcolato dalla **data di creazione** "
        "del ticket alla prima transizione verso uno stato operativo, ad esempio "
        "**Analisi**, **In corso**, **In revisione/Test**, **ON HOLD TEMP** "
        "o **BLOCCATO**. "
        "Sono conteggiate solo le ore lavorative **09:00–13:00** e "
        "**14:00–18:00**, dal lunedì al venerdì."
    )

    if issue_df.empty:
        st.info("Nessuna issue disponibile per i filtri selezionati.")
        return

    task_bug_df = filter_task_bug(issue_df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    issue_signature = "|".join(
        sorted(
            task_bug_df["Issue"]
            .dropna()
            .drop_duplicates()
            .astype(str)
            .tolist()
        )
    )

    previous_signature = st.session_state.get("pickup_time_signature")

    if previous_signature != issue_signature:
        st.session_state["pickup_time_signature"] = issue_signature
        st.session_state["pickup_time_loaded"] = False

        if "pickup_time_df" in st.session_state:
            del st.session_state["pickup_time_df"]

    calculate = st.button(
        "Calcola / aggiorna tempi di presa in carico",
        key="calculate_pickup_time_button",
        use_container_width=False,
    )

    if calculate:
        st.session_state["pickup_time_loaded"] = True

        pickup_df = build_pickup_time_dataframe(
            issue_df=task_bug_df,
            jira_domain=jira_domain,
            jira_email=jira_email,
            jira_api_token=jira_api_token,
        )

        st.session_state["pickup_time_df"] = pickup_df

    if not st.session_state.get("pickup_time_loaded", False):
        st.info(
            "Premi **Calcola / aggiorna tempi di presa in carico** "
            "per recuperare la changelog Jira e calcolare i tempi."
        )
        return

    pickup_df = st.session_state.get("pickup_time_df")

    if pickup_df is None or pickup_df.empty:
        st.info("Nessun tempo di presa in carico disponibile.")
        return

    calculated_df = pickup_df[
        pickup_df["Esito"].isin(CALCULATED_ESITI)
    ].copy()

    summary_df = build_priority_pickup_summary(pickup_df)

    st.divider()

    st.subheader("Tempo medio di presa in carico per priorità")

    card_columns = st.columns(5)

    priority_colors = {
        "Altissima": ("#DC2626", "#FEF2F2"),
        "Alta": ("#F97316", "#FFF7ED"),
        "Media": ("#CA8A04", "#FEFCE8"),
        "Bassa": ("#16A34A", "#ECFDF3"),
        "Fase 2": ("#0284C7", "#F0F9FF"),
    }

    for index, priority in enumerate(PRIORITY_ORDER):
        value, count = get_average_pickup_days_for_priority(
            summary_df,
            priority,
        )

        color, background = priority_colors.get(
            priority,
            ("#172033", "#ffffff"),
        )

        with card_columns[index]:
            render_metric_card(
                label=f"{priority} ({count} ticket)",
                value=format_days_value(value),
                color=color,
                background=background,
            )

    st.caption(
        "Le card mostrano il **tempo medio di presa in carico** per priorità "
        "cliente, considerando solo i ticket per cui è stata trovata una "
        "transizione verso uno stato operativo."
    )

    st.divider()

    st.subheader("Riepilogo per priorità")

    if summary_df.empty:
        st.info("Nessun ticket calcolato disponibile per il riepilogo.")
    else:
        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
            key="pickup_time_priority_summary_table",
            column_config={
                "Tempo medio presa in carico giorni": st.column_config.NumberColumn(
                    "Tempo medio presa in carico giorni lav.",
                    format="%.3f",
                ),
                "Tempo medio presa in carico ore": st.column_config.NumberColumn(
                    "Tempo medio presa in carico ore lav.",
                    format="%.2f",
                ),
                "Tempo mediano presa in carico giorni": st.column_config.NumberColumn(
                    "Tempo mediano presa in carico giorni lav.",
                    format="%.3f",
                ),
                "Tempo massimo presa in carico giorni": st.column_config.NumberColumn(
                    "Tempo massimo presa in carico giorni lav.",
                    format="%.3f",
                ),
            },
        )

    st.divider()

    st.subheader("Esiti calcolo")

    esiti_df = build_esiti_summary(pickup_df)

    st.dataframe(
        esiti_df,
        use_container_width=True,
        hide_index=True,
        key="pickup_time_esiti_table",
    )

    st.divider()

    st.subheader("Dettaglio ticket")

    detail_df = prepare_pickup_detail_for_display(pickup_df)

    columns = [
        "Issue",
        "Summary",
        "Assegnatario",
        "Priorità cliente",
        "Data creazione",
        "Data presa in carico",
        "Stato presa in carico",
        "Tempo presa in carico ore",
        "Tempo presa in carico giorni",
        "Esito",
        "Url",
    ]

    existing_columns = [
        column
        for column in columns
        if column in detail_df.columns
    ]

    st.dataframe(
        detail_df[existing_columns],
        use_container_width=True,
        hide_index=True,
        key="pickup_time_detail_table",
        column_config={
            "Tempo presa in carico ore": st.column_config.NumberColumn(
                "Tempo presa in carico ore lav.",
                format="%.2f",
            ),
            "Tempo presa in carico giorni": st.column_config.NumberColumn(
                "Tempo presa in carico giorni lav.",
                format="%.3f",
            ),
            "Url": st.column_config.LinkColumn("Jira"),
        },
    )
