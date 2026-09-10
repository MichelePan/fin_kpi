import html
import io
import re
import unicodedata
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

from requests.auth import HTTPBasicAuth

# ======================
# CONFIG ISSUE TYPE
# ======================

EXCLUDED_ISSUE_TYPES = {
    "EPIC",
    "EPICA",
}

# ======================
# CONFIG STATI
# ======================

OPENING_STATUSES = {
    "DA FARE",
}

EXECUTION_STATUSES = {
    "ANALISI",
    "ANALISI PRELIMINARE",
    "IN CORSO",
    "IN REVISIONE/TEST",
}

EXCLUDED_STATUSES = {
    "ON HOLD TEMP",
    "BLOCCATO",
}

CLOSING_STATUSES = {
    "DONE",
    "CHIUSO",
    "VERBALE CHIUSO",
    "FATTO",
    "TICKET FIL NON CHIUSO",
    "ANNULLATO",
}

WORKING_HOURS_PER_DAY = 8
MONTHLY_TREND_START_MONTH = 6

CALCULATED_ESITI = {
    "Calcolato",
    "Calcolato tramite resolutiondate",
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
    return normalize_text(value)

def normalize_status(value) -> str:
    return normalize_text(value)

def is_excluded_issue_type(issue_type) -> bool:
    return normalize_issue_type(issue_type) in EXCLUDED_ISSUE_TYPES

def is_opening_status(status) -> bool:
    return normalize_status(status) in OPENING_STATUSES

def is_execution_status(status) -> bool:
    return normalize_status(status) in EXECUTION_STATUSES

def is_closing_status(status) -> bool:
    return normalize_status(status) in CLOSING_STATUSES

def is_completed_issue(issue_info: dict) -> bool:
    done_value = issue_info.get("Done", False)

    if bool(done_value) is True:
        return True

    current_status = issue_info.get("Stato", "")

    if is_closing_status(current_status):
        return True

    status_category = issue_info.get("StatusCategory", "")

    if normalize_status(status_category) == "DONE":
        return True

    return False

def seconds_to_hours(seconds: float) -> float:
    return round(seconds / 3600, 2)

def hours_to_working_days(hours: float) -> float:
    return round(hours / WORKING_HOURS_PER_DAY, 2)

def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default

        return float(value)
    except Exception:
        return default

def get_estimate_hours(issue_info: dict) -> float:
    estimate = issue_info.get("StimaOre", None)

    if estimate is None:
        estimate = issue_info.get("Stima (in ore)", 0)

    return round(safe_float(estimate, 0.0), 2)

def get_spent_hours(issue_info: dict) -> float:
    spent = issue_info.get("TempoImpiegatoOre", None)

    if spent is None:
        spent = issue_info.get("Tempo impiegato (in ore)", None)

    if spent is None:
        spent = issue_info.get("Tempo impiegato ore", 0)

    return round(safe_float(spent, 0.0), 2)

def build_epic_label(issue_info: dict) -> str:
    epic_name = str(issue_info.get("EpicName", "") or "").strip()
    epic_key = str(issue_info.get("EpicKey", "") or "").strip()

    if epic_name and epic_key:
        return f"{epic_key} - {epic_name}"

    if epic_name:
        return epic_name

    if epic_key:
        return epic_key

    return "Senza Epic"

def ensure_epic_column(df: pd.DataFrame) -> pd.DataFrame:
    updated_df = df.copy()

    if "Epic" in updated_df.columns:
        updated_df["Epic"] = (
            updated_df["Epic"]
            .fillna("")
            .replace("", "Senza Epic")
        )
        return updated_df

    updated_df["Epic"] = updated_df.apply(
        lambda row: build_epic_label(row.to_dict()),
        axis=1,
    )

    return updated_df

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

def find_start_event(events: list[dict]):
    for event in events:
        from_status = event.get("FromStatusNormalized", "")
        to_status = event.get("ToStatusNormalized", "")

        if from_status in OPENING_STATUSES and to_status in EXECUTION_STATUSES:
            return event

    return None

def get_effective_closing_statuses(issue_info: dict) -> set[str]:
    effective_closing_statuses = set(CLOSING_STATUSES)

    if is_completed_issue(issue_info):
        current_status = normalize_status(issue_info.get("Stato", ""))

        if current_status:
            effective_closing_statuses.add(current_status)

    return effective_closing_statuses

def find_end_and_excluded_time(
    events: list[dict],
    start_event: dict,
    issue_info: dict,
):
    start_ts = start_event["Timestamp"]

    current_status = start_event.get("ToStatusNormalized", "")
    previous_ts = start_ts

    end_ts = pd.NaT
    end_status = ""
    excluded_seconds = 0.0

    effective_closing_statuses = get_effective_closing_statuses(issue_info)

    events_after_start = [
        event
        for event in events
        if event["Timestamp"] > start_ts
    ]

    for event in events_after_start:
        event_ts = event["Timestamp"]

        if event_ts < previous_ts:
            continue

        if current_status in EXCLUDED_STATUSES:
            interval_seconds = (event_ts - previous_ts).total_seconds()
            excluded_seconds += max(interval_seconds, 0)

        to_status = event.get("ToStatusNormalized", "")

        if to_status in effective_closing_statuses:
            end_ts = event_ts
            end_status = event.get("ToStatus", "")
            break

        current_status = to_status
        previous_ts = event_ts

    return end_ts, end_status, excluded_seconds

def get_resolution_date_from_issue(issue_info: dict):
    possible_keys = [
        "ResolutionDate",
        "Data risoluzione",
        "resolutiondate",
    ]

    for key in possible_keys:
        if key not in issue_info:
            continue

        value = issue_info.get(key)

        if value is None or value == "":
            continue

        parsed_value = pd.to_datetime(
            value,
            utc=True,
            errors="coerce",
        )

        if not pd.isna(parsed_value):
            return parsed_value

    return pd.NaT

def estimate_excluded_time_until_end(
    events: list[dict],
    start_event: dict,
    end_ts,
):
    start_ts = start_event["Timestamp"]

    current_status = start_event.get("ToStatusNormalized", "")
    previous_ts = start_ts
    excluded_seconds = 0.0

    events_after_start = [
        event
        for event in events
        if event["Timestamp"] > start_ts and event["Timestamp"] <= end_ts
    ]

    for event in events_after_start:
        event_ts = event["Timestamp"]

        if event_ts < previous_ts:
            continue

        if current_status in EXCLUDED_STATUSES:
            interval_seconds = (event_ts - previous_ts).total_seconds()
            excluded_seconds += max(interval_seconds, 0)

        current_status = event.get("ToStatusNormalized", "")
        previous_ts = event_ts

    if current_status in EXCLUDED_STATUSES and end_ts > previous_ts:
        interval_seconds = (end_ts - previous_ts).total_seconds()
        excluded_seconds += max(interval_seconds, 0)

    return excluded_seconds

# ======================
# CALCOLO TEMPI RISOLUZIONE
# ======================

def compute_resolution_time_for_issue(
    issue_info: dict,
    changelog: list[dict],
) -> dict:
    issue_key = issue_info.get("Issue", "")
    stima_ore = get_estimate_hours(issue_info)
    tempo_impiegato_ore = get_spent_hours(issue_info)

    result = {
        "Issue": issue_key,
        "Summary": issue_info.get("Summary", ""),
        "IssueType": issue_info.get("IssueType", ""),
        "Stato corrente": issue_info.get("Stato", ""),
        "Assignee": issue_info.get("Assignee", ""),
        "EpicKey": issue_info.get("EpicKey", ""),
        "EpicName": issue_info.get("EpicName", ""),
        "Epic": build_epic_label(issue_info),
        "StimaOre": stima_ore,
        "Tempo impiegato ore": tempo_impiegato_ore,
        "Data inizio lavorazione": pd.NaT,
        "Data fine lavorazione": pd.NaT,
        "Stato fine": "",
        "Tempo lordo giorni": None,
        "Tempo lordo ore": None,
        "Tempo escluso giorni": None,
        "Tempo escluso ore": None,
        "Tempo netto giorni": None,
        "Tempo netto ore": None,
        "Entro stima": calculate_estimate_status(stima_ore, tempo_impiegato_ore),
        "Scostamento ore": calculate_estimate_delta(stima_ore, tempo_impiegato_ore),
        "Esito": "",
        "Url": issue_info.get("Url", ""),
    }

    if is_excluded_issue_type(issue_info.get("IssueType", "")):
        result["Esito"] = "Escluso: Epic"
        return result

    if not is_completed_issue(issue_info):
        result["Esito"] = "Escluso: ticket non completato"
        return result

    events = extract_status_events(changelog)

    if not events:
        result["Esito"] = "Changelog stato non disponibile"
        return result

    start_event = find_start_event(events)

    if start_event is None:
        result["Esito"] = "Transizione apertura → esecuzione non trovata"
        return result

    start_ts = start_event["Timestamp"]

    end_ts, end_status, excluded_seconds = find_end_and_excluded_time(
        events=events,
        start_event=start_event,
        issue_info=issue_info,
    )

    end_source = "transizione"

    if pd.isna(end_ts):
        resolution_date = get_resolution_date_from_issue(issue_info)

        if not pd.isna(resolution_date):
            end_ts = resolution_date
            end_status = issue_info.get("Stato", "")
            excluded_seconds = estimate_excluded_time_until_end(
                events=events,
                start_event=start_event,
                end_ts=end_ts,
            )
            end_source = "resolutiondate"

    result["Data inizio lavorazione"] = start_ts

    if pd.isna(end_ts):
        result["Esito"] = "Transizione verso stato di chiusura non trovata"
        return result

    result["Data fine lavorazione"] = end_ts
    result["Stato fine"] = end_status

    gross_seconds = max(
        (end_ts - start_ts).total_seconds(),
        0,
    )

    net_seconds = max(
        gross_seconds - excluded_seconds,
        0,
    )

    gross_hours = seconds_to_hours(gross_seconds)
    excluded_hours = seconds_to_hours(excluded_seconds)
    net_hours = seconds_to_hours(net_seconds)

    result["Tempo lordo ore"] = gross_hours
    result["Tempo lordo giorni"] = hours_to_working_days(gross_hours)

    result["Tempo escluso ore"] = excluded_hours
    result["Tempo escluso giorni"] = hours_to_working_days(excluded_hours)

    result["Tempo netto ore"] = net_hours
    result["Tempo netto giorni"] = hours_to_working_days(net_hours)

    if end_source == "resolutiondate":
        result["Esito"] = "Calcolato tramite resolutiondate"
    else:
        result["Esito"] = "Calcolato"

    return result

def filter_completed_non_epic_issues(issue_df: pd.DataFrame) -> pd.DataFrame:
    if issue_df.empty:
        return issue_df.copy()

    filtered_df = issue_df.copy()

    filtered_df = filtered_df[
        ~filtered_df["IssueType"].apply(is_excluded_issue_type)
    ]

    filtered_df = filtered_df[
        filtered_df.apply(
            lambda row: is_completed_issue(row.to_dict()),
            axis=1,
        )
    ]

    return filtered_df.copy()

def build_resolution_time_dataframe(
    issue_df: pd.DataFrame,
    jira_domain: str,
    jira_email: str,
    jira_api_token: str,
) -> pd.DataFrame:
    columns = [
        "Issue",
        "Summary",
        "IssueType",
        "Stato corrente",
        "Assignee",
        "EpicKey",
        "EpicName",
        "Epic",
        "StimaOre",
        "Tempo impiegato ore",
        "Data inizio lavorazione",
        "Data fine lavorazione",
        "Stato fine",
        "Tempo lordo giorni",
        "Tempo lordo ore",
        "Tempo escluso giorni",
        "Tempo escluso ore",
        "Tempo netto giorni",
        "Tempo netto ore",
        "Entro stima",
        "Scostamento ore",
        "Esito",
        "Url",
    ]

    if issue_df.empty:
        return pd.DataFrame(columns=columns)

    completed_issue_df = filter_completed_non_epic_issues(issue_df)

    if completed_issue_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    issue_records = completed_issue_df.to_dict(orient="records")
    total_issues = len(issue_records)

    progress_text = st.empty()
    progress_bar = st.progress(0)

    for index, issue_info in enumerate(issue_records, start=1):
        issue_key = issue_info.get("Issue", "")

        progress_text.write(
            f"Calcolo tempi {index}/{total_issues}: {issue_key}"
        )

        try:
            changelog = get_issue_changelog(
                jira_domain,
                jira_email,
                jira_api_token,
                issue_key,
            )
        except Exception as exc:
            row = {
                "Issue": issue_key,
                "Summary": issue_info.get("Summary", ""),
                "IssueType": issue_info.get("IssueType", ""),
                "Stato corrente": issue_info.get("Stato", ""),
                "Assignee": issue_info.get("Assignee", ""),
                "EpicKey": issue_info.get("EpicKey", ""),
                "EpicName": issue_info.get("EpicName", ""),
                "Epic": build_epic_label(issue_info),
                "StimaOre": get_estimate_hours(issue_info),
                "Tempo impiegato ore": get_spent_hours(issue_info),
                "Data inizio lavorazione": pd.NaT,
                "Data fine lavorazione": pd.NaT,
                "Stato fine": "",
                "Tempo lordo giorni": None,
                "Tempo lordo ore": None,
                "Tempo escluso giorni": None,
                "Tempo escluso ore": None,
                "Tempo netto giorni": None,
                "Tempo netto ore": None,
                "Entro stima": calculate_estimate_status(
                    get_estimate_hours(issue_info),
                    get_spent_hours(issue_info),
                ),
                "Scostamento ore": calculate_estimate_delta(
                    get_estimate_hours(issue_info),
                    get_spent_hours(issue_info),
                ),
                "Esito": f"Errore recupero changelog: {str(exc)[:180]}",
                "Url": issue_info.get("Url", ""),
            }

            rows.append(row)
            progress_bar.progress(index / total_issues)
            continue

        row = compute_resolution_time_for_issue(
            issue_info=issue_info,
            changelog=changelog,
        )

        rows.append(row)
        progress_bar.progress(index / total_issues)

    progress_text.empty()
    progress_bar.empty()

    result_df = pd.DataFrame(rows, columns=columns)

    if result_df.empty:
        return result_df

    result_df = ensure_epic_column(result_df)

    result_df["Data inizio lavorazione"] = pd.to_datetime(
        result_df["Data inizio lavorazione"],
        errors="coerce",
    )

    result_df["Data fine lavorazione"] = pd.to_datetime(
        result_df["Data fine lavorazione"],
        errors="coerce",
    )

    numeric_columns = [
        "StimaOre",
        "Tempo impiegato ore",
        "Tempo lordo giorni",
        "Tempo lordo ore",
        "Tempo escluso giorni",
        "Tempo escluso ore",
        "Tempo netto giorni",
        "Tempo netto ore",
        "Scostamento ore",
    ]

    for column in numeric_columns:
        result_df[column] = pd.to_numeric(
            result_df[column],
            errors="coerce",
        )

    return result_df

# ======================
# RISPETTO STIME
# ======================

def calculate_estimate_status(stima_ore: float, tempo_impiegato_ore: float) -> str:
    stima_ore = safe_float(stima_ore, 0.0)
    tempo_impiegato_ore = safe_float(tempo_impiegato_ore, 0.0)

    if stima_ore <= 0:
        return "Stima non valorizzata"

    if tempo_impiegato_ore <= stima_ore:
        return "Sì"

    return "No"

def calculate_estimate_delta(stima_ore: float, tempo_impiegato_ore: float):
    stima_ore = safe_float(stima_ore, 0.0)
    tempo_impiegato_ore = safe_float(tempo_impiegato_ore, 0.0)

    if stima_ore <= 0:
        return None

    return round(tempo_impiegato_ore - stima_ore, 2)

def build_estimate_compliance_dataframe(issue_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Issue",
        "Summary",
        "IssueType",
        "Stato",
        "Assignee",
        "Epic",
        "StimaOre",
        "Tempo impiegato ore",
        "Entro stima",
        "Scostamento ore",
        "Url",
    ]

    if issue_df.empty:
        return pd.DataFrame(columns=columns)

    estimate_df = issue_df.copy()
    estimate_df = ensure_epic_column(estimate_df)

    estimate_df["StimaOre"] = estimate_df.apply(
        lambda row: get_estimate_hours(row.to_dict()),
        axis=1,
    )

    estimate_df["Tempo impiegato ore"] = estimate_df.apply(
        lambda row: get_spent_hours(row.to_dict()),
        axis=1,
    )

    estimate_df = estimate_df[
        estimate_df["StimaOre"] > 0
    ].copy()

    if estimate_df.empty:
        return pd.DataFrame(columns=columns)

    estimate_df["Entro stima"] = estimate_df.apply(
        lambda row: calculate_estimate_status(
            row["StimaOre"],
            row["Tempo impiegato ore"],
        ),
        axis=1,
    )

    estimate_df["Scostamento ore"] = estimate_df.apply(
        lambda row: calculate_estimate_delta(
            row["StimaOre"],
            row["Tempo impiegato ore"],
        ),
        axis=1,
    )

    estimate_df = estimate_df[columns].copy()

    estimate_df = estimate_df.sort_values(
        by=["Entro stima", "Scostamento ore", "Issue"],
        ascending=[True, False, True],
    )

    return estimate_df

def build_estimate_compliance_summary(issue_df: pd.DataFrame) -> dict:
    result = {
        "ticket_con_stima": 0,
        "entro_stima": 0,
        "sforati": 0,
        "percentuale_entro_stima": 0.0,
    }

    estimate_df = build_estimate_compliance_dataframe(issue_df)

    if estimate_df.empty:
        return result

    ticket_con_stima = len(estimate_df)
    entro_stima = int((estimate_df["Entro stima"] == "Sì").sum())
    sforati = int((estimate_df["Entro stima"] == "No").sum())

    percentuale_entro_stima = round(
        entro_stima / ticket_con_stima * 100,
        1,
    )

    result["ticket_con_stima"] = ticket_con_stima
    result["entro_stima"] = entro_stima
    result["sforati"] = sforati
    result["percentuale_entro_stima"] = percentuale_entro_stima

    return result

# ======================
# AGGREGAZIONI
# ======================

def build_epic_resolution_summary(
    calculated_df: pd.DataFrame,
    estimate_source_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    columns = [
        "Epic",
        "Ticket calcolati",
        "Ticket con stima",
        "Chiusi entro stima",
        "Sforati",
        "% entro stima",
        "Tempo medio netto giorni",
        "Tempo mediano netto giorni",
        "Tempo massimo netto giorni",
        "Tempo medio netto ore",
        "Tempo impiegato medio ore",
        "Tempo escluso medio giorni",
    ]

    if calculated_df.empty:
        return pd.DataFrame(columns=columns)

    safe_df = ensure_epic_column(calculated_df)

    if estimate_source_df is None:
        estimate_source_df = safe_df

    estimate_source_df = ensure_epic_column(estimate_source_df)

    summary_rows = []

    for epic, epic_df in safe_df.groupby("Epic", dropna=False):
        epic_estimate_source_df = estimate_source_df[
            estimate_source_df["Epic"] == epic
        ].copy()

        estimate_summary = build_estimate_compliance_summary(
            epic_estimate_source_df
        )

        row = {
            "Epic": epic,
            "Ticket calcolati": len(epic_df),
            "Ticket con stima": estimate_summary["ticket_con_stima"],
            "Chiusi entro stima": estimate_summary["entro_stima"],
            "Sforati": estimate_summary["sforati"],
            "% entro stima": estimate_summary["percentuale_entro_stima"],
            "Tempo medio netto giorni": round(epic_df["Tempo netto giorni"].mean(), 2),
            "Tempo mediano netto giorni": round(epic_df["Tempo netto giorni"].median(), 2),
            "Tempo massimo netto giorni": round(epic_df["Tempo netto giorni"].max(), 2),
            "Tempo medio netto ore": round(epic_df["Tempo netto ore"].mean(), 2),
            "Tempo impiegato medio ore": round(
                epic_estimate_source_df["TempoImpiegatoOre"].mean(), 2
            ) if "TempoImpiegatoOre" in epic_estimate_source_df.columns else 0,
            "Tempo escluso medio giorni": round(epic_df["Tempo escluso giorni"].mean(), 2),
        }

        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows, columns=columns)

    summary_df = summary_df.sort_values(
        by=["Tempo medio netto giorni", "Ticket calcolati"],
        ascending=[False, False],
    )

    return summary_df[columns]

def build_monthly_resolution_summary_by_epic(
    calculated_df: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "Mese",
        "Epic",
        "Ticket calcolati",
        "Tempo medio netto giorni",
        "Tempo mediano netto giorni",
        "Tempo massimo netto giorni",
        "Tempo medio netto ore",
        "Tempo escluso medio giorni",
    ]

    if calculated_df.empty:
        return pd.DataFrame(columns=columns)

    monthly_df = ensure_epic_column(calculated_df)

    monthly_df["Data fine lavorazione"] = pd.to_datetime(
        monthly_df["Data fine lavorazione"],
        utc=True,
        errors="coerce",
    )

    monthly_df = monthly_df.dropna(subset=["Data fine lavorazione"])

    if monthly_df.empty:
        return pd.DataFrame(columns=columns)

    monthly_df["Data fine lavorazione"] = (
        monthly_df["Data fine lavorazione"]
        .dt.tz_convert(None)
    )

    today = pd.Timestamp.today().normalize()
    start_date = pd.Timestamp(
        year=today.year,
        month=MONTHLY_TREND_START_MONTH,
        day=1,
    )

    monthly_df = monthly_df[
        monthly_df["Data fine lavorazione"] >= start_date
    ]

    monthly_df = monthly_df[
        monthly_df["Data fine lavorazione"] <= today + pd.Timedelta(days=1)
    ]

    if monthly_df.empty:
        return pd.DataFrame(columns=columns)

    monthly_df["Mese"] = (
        monthly_df["Data fine lavorazione"]
        .dt.to_period("M")
        .astype(str)
    )

    summary_df = (
        monthly_df
        .groupby(["Mese", "Epic"], dropna=False)
        .agg(
            **{
                "Ticket calcolati": ("Issue", "count"),
                "Tempo medio netto giorni": ("Tempo netto giorni", "mean"),
                "Tempo mediano netto giorni": ("Tempo netto giorni", "median"),
                "Tempo massimo netto giorni": ("Tempo netto giorni", "max"),
                "Tempo medio netto ore": ("Tempo netto ore", "mean"),
                "Tempo escluso medio giorni": ("Tempo escluso giorni", "mean"),
            }
        )
        .reset_index()
        .sort_values(["Mese", "Epic"])
    )

    numeric_columns = [
        "Tempo medio netto giorni",
        "Tempo mediano netto giorni",
        "Tempo massimo netto giorni",
        "Tempo medio netto ore",
        "Tempo escluso medio giorni",
    ]

    for column in numeric_columns:
        summary_df[column] = summary_df[column].round(2)

    return summary_df[columns]

# ======================
# EXPORT
# ======================

def make_datetime_excel_safe(value):
    if value is None or pd.isna(value):
        return pd.NaT

    parsed_value = pd.to_datetime(
        value,
        errors="coerce",
    )

    if pd.isna(parsed_value):
        return pd.NaT

    if getattr(parsed_value, "tzinfo", None) is not None:
        parsed_value = parsed_value.tz_convert(None)

    return parsed_value

def prepare_resolution_dataframe_for_excel(
    resolution_df: pd.DataFrame,
) -> pd.DataFrame:
    export_df = resolution_df.copy()
    export_df = ensure_epic_column(export_df)

    datetime_columns = [
        "Data inizio lavorazione",
        "Data fine lavorazione",
    ]

    for column in datetime_columns:
        if column in export_df.columns:
            export_df[column] = export_df[column].apply(make_datetime_excel_safe)

    return export_df

def create_resolution_time_excel_export(
    resolution_df: pd.DataFrame,
    estimate_df: pd.DataFrame | None = None,
):
    output = io.BytesIO()

    export_df = prepare_resolution_dataframe_for_excel(resolution_df)

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        export_df.to_excel(
            writer,
            index=False,
            sheet_name="Tempi risoluzione",
        )

        calculated_df = export_df[
            export_df["Esito"].isin(CALCULATED_ESITI)
        ].copy()

        epic_summary_df = build_epic_resolution_summary(calculated_df)
        monthly_summary_df = build_monthly_resolution_summary_by_epic(calculated_df)

        if not epic_summary_df.empty:
            epic_summary_df.to_excel(
                writer,
                index=False,
                sheet_name="Tempi per Epic",
            )

        if not monthly_summary_df.empty:
            monthly_summary_df.to_excel(
                writer,
                index=False,
                sheet_name="Andamento mensile",
            )

        if estimate_df is not None and not estimate_df.empty:
            estimate_df.to_excel(
                writer,
                index=False,
                sheet_name="Rispetto stime",
            )

        workbook = writer.book

        number_format = workbook.add_format(
            {
                "num_format": "0.00",
            }
        )

        datetime_format = workbook.add_format(
            {
                "num_format": "dd/mm/yyyy hh:mm",
            }
        )

        resolution_sheet = writer.sheets["Tempi risoluzione"]

        resolution_sheet.set_column("A:A", 14)
        resolution_sheet.set_column("B:B", 60)
        resolution_sheet.set_column("C:E", 18)
        resolution_sheet.set_column("F:H", 28)
        resolution_sheet.set_column("I:J", 18, number_format)
        resolution_sheet.set_column("K:L", 22, datetime_format)
        resolution_sheet.set_column("M:M", 18)
        resolution_sheet.set_column("N:S", 18, number_format)
        resolution_sheet.set_column("T:T", 18)
        resolution_sheet.set_column("U:U", 18, number_format)
        resolution_sheet.set_column("V:V", 46)
        resolution_sheet.set_column("W:W", 60)

        if "Tempi per Epic" in writer.sheets:
            epic_sheet = writer.sheets["Tempi per Epic"]
            epic_sheet.set_column("A:A", 50)
            epic_sheet.set_column("B:E", 18)
            epic_sheet.set_column("F:F", 18, number_format)
            epic_sheet.set_column("G:L", 24, number_format)

        if "Andamento mensile" in writer.sheets:
            monthly_sheet = writer.sheets["Andamento mensile"]
            monthly_sheet.set_column("A:A", 14)
            monthly_sheet.set_column("B:B", 50)
            monthly_sheet.set_column("C:C", 18)
            monthly_sheet.set_column("D:H", 26, number_format)

        if "Rispetto stime" in writer.sheets:
            estimate_sheet = writer.sheets["Rispetto stime"]
            estimate_sheet.set_column("A:A", 14)
            estimate_sheet.set_column("B:B", 60)
            estimate_sheet.set_column("C:F", 24)
            estimate_sheet.set_column("G:H", 20, number_format)
            estimate_sheet.set_column("I:I", 16)
            estimate_sheet.set_column("J:J", 20, number_format)
            estimate_sheet.set_column("K:K", 60)

    output.seek(0)

    return output

# ======================
# UI
# ======================

def render_resolution_time_section(
    issue_df: pd.DataFrame,
    jira_domain: str,
    jira_email: str,
    jira_api_token: str,
):
    st.subheader("Tempi di risoluzione")

    st.caption(
        "Il tempo di risoluzione viene calcolato sui ticket completati, escludendo le Epic. "
        "Il calcolo parte dalla prima transizione da uno stato di apertura "
        "a uno stato di esecuzione. "
        "Il tempo trascorso negli stati **ON HOLD TEMP** e **BLOCCATO** "
        "viene escluso dal calcolo netto. "
        "I giorni mostrati sono **giorni lavorativi equivalenti da 8 ore**, "
        "non giorni solari. "
        "Il rispetto stime viene calcolato separatamente, confrontando solo "
        "**tempo stimato Jira** e **tempo impiegato Jira**."
    )

    if issue_df.empty:
        st.info("Nessuna issue disponibile per i filtri selezionati.")
        return

    completed_issue_df = filter_completed_non_epic_issues(issue_df)

    if completed_issue_df.empty:
        st.info(
            "Nessun ticket completato disponibile per il calcolo "
            "dei tempi di risoluzione."
        )
        return

    total_visible_issues = len(issue_df)
    total_completed_issues = len(completed_issue_df)

    st.caption(
        f"Ticket nel perimetro filtrato: **{total_visible_issues}** · "
        f"Ticket completati analizzati, escluse Epic: **{total_completed_issues}**"
    )

    estimate_df = build_estimate_compliance_dataframe(completed_issue_df)
    estimate_summary = build_estimate_compliance_summary(completed_issue_df)

    with st.expander("Diagnostica ticket considerati", expanded=False):
        issue_type_df = (
            completed_issue_df
            .groupby("IssueType", dropna=False)
            .size()
            .reset_index(name="Ticket completati")
            .sort_values("Ticket completati", ascending=False)
        )

        status_df = (
            completed_issue_df
            .groupby("Stato", dropna=False)
            .size()
            .reset_index(name="Ticket completati")
            .sort_values("Ticket completati", ascending=False)
        )

        epic_df = completed_issue_df.copy()
        epic_df["Epic"] = epic_df.apply(
            lambda row: build_epic_label(row.to_dict()),
            axis=1,
        )

        epic_count_df = (
            epic_df
            .groupby("Epic", dropna=False)
            .size()
            .reset_index(name="Ticket completati")
            .sort_values("Ticket completati", ascending=False)
        )

        col1, col2 = st.columns(2)

        with col1:
            st.write("Completati per Issue Type")
            st.dataframe(
                issue_type_df,
                use_container_width=True,
                hide_index=True,
                key="resolution_time_diagnostic_issue_type",
            )

        with col2:
            st.write("Completati per Stato")
            st.dataframe(
                status_df,
                use_container_width=True,
                hide_index=True,
                key="resolution_time_diagnostic_status",
            )

        st.write("Completati per Epic")
        st.dataframe(
            epic_count_df,
            use_container_width=True,
            hide_index=True,
            key="resolution_time_diagnostic_epic",
        )

    issue_signature = "|".join(
        sorted(
            completed_issue_df["Issue"]
            .dropna()
            .drop_duplicates()
            .astype(str)
            .tolist()
        )
    )

    previous_signature = st.session_state.get("resolution_time_signature")

    if previous_signature != issue_signature:
        st.session_state["resolution_time_signature"] = issue_signature
        st.session_state["resolution_time_loaded"] = False

        if "resolution_time_df" in st.session_state:
            del st.session_state["resolution_time_df"]

    calculate = st.button(
        "Calcola / aggiorna tempi di risoluzione",
        key="calculate_resolution_time_button",
        use_container_width=False,
    )

    if calculate:
        st.session_state["resolution_time_loaded"] = True

        resolution_df = build_resolution_time_dataframe(
            issue_df=completed_issue_df,
            jira_domain=jira_domain,
            jira_email=jira_email,
            jira_api_token=jira_api_token,
        )

        resolution_df = ensure_epic_column(resolution_df)
        st.session_state["resolution_time_df"] = resolution_df

    if not st.session_state.get("resolution_time_loaded", False):
        st.info(
            "Premi **Calcola / aggiorna tempi di risoluzione** per recuperare "
            "la changelog Jira dei ticket completati e calcolare i tempi."
        )

        st.divider()

        st.subheader("Rispetto stime")

        render_estimate_compliance_cards(estimate_summary)

        st.caption(
            "Questa sezione è calcolata direttamente dai campi Jira "
            "**tempo stimato** e **tempo impiegato**. "
            "I ticket con stima nulla o pari a 0 minuti sono esclusi."
        )

        render_estimate_detail_table(estimate_df)

        return

    resolution_df = st.session_state.get("resolution_time_df")

    if resolution_df is None or resolution_df.empty:
        st.info("Nessun tempo di risoluzione disponibile.")
        return

    resolution_df = ensure_epic_column(resolution_df)

    calculated_df = resolution_df[
        resolution_df["Esito"].isin(CALCULATED_ESITI)
    ].copy()

    calculated_df = ensure_epic_column(calculated_df)

    total_rows = len(resolution_df)
    calculated_tickets = len(calculated_df)
    not_calculated_tickets = total_rows - calculated_tickets

    average_days = 0
    average_hours = 0
    median_days = 0
    max_days = 0
    excluded_average_days = 0

    if not calculated_df.empty:
        average_days = round(
            calculated_df["Tempo netto giorni"].mean(),
            2,
        )

        average_hours = round(
            calculated_df["Tempo netto ore"].mean(),
            2,
        )

        median_days = round(
            calculated_df["Tempo netto giorni"].median(),
            2,
        )

        max_days = round(
            calculated_df["Tempo netto giorni"].max(),
            2,
        )

        excluded_average_days = round(
            calculated_df["Tempo escluso giorni"].mean(),
            2,
        )

    t1, t2, t3, t4 = st.columns(4)

    with t1:
        render_metric_card(
            label="Tempo medio risoluzione",
            value=f"{average_days} giorni lav.",
            color="#2563EB",
            background="#EFF6FF",
        )

    with t2:
        render_metric_card(
            label="Tempo medio risoluzione ore",
            value=f"{average_hours} ore",
            color="#2563EB",
            background="#EFF6FF",
        )

    with t3:
        render_metric_card(
            label="Ticket calcolati",
            value=calculated_tickets,
            color="#027A48",
            background="#ECFDF3",
        )

    with t4:
        render_metric_card(
            label="Ticket non calcolati",
            value=max(not_calculated_tickets, 0),
            color="#B42318" if not_calculated_tickets > 0 else "#027A48",
            background="#FEF3F2" if not_calculated_tickets > 0 else "#ECFDF3",
        )

    t5, t6, t7, t8 = st.columns(4)

    with t5:
        render_metric_card(
            label="Mediana risoluzione",
            value=f"{median_days} giorni lav.",
            color="#2563EB",
            background="#EFF6FF",
        )

    with t6:
        render_metric_card(
            label="Ticket completati analizzati",
            value=total_rows,
        )

    with t7:
        render_metric_card(
            label="Tempo massimo netto",
            value=f"{max_days} giorni lav.",
            color="#B54708",
            background="#FFFAEB",
        )

    with t8:
        render_metric_card(
            label="Tempo escluso medio",
            value=f"{excluded_average_days} giorni lav.",
            color="#B54708",
            background="#FFFAEB",
        )

    st.divider()

    st.subheader("Rispetto stime")

    render_estimate_compliance_cards(estimate_summary)

    st.caption(
        "Il confronto considera solo i ticket completati con **tempo stimato > 0**. "
        "Un ticket è considerato entro stima se il **tempo impiegato Jira** "
        "è minore o uguale al **tempo stimato Jira**. "
        "I ticket con stima nulla o pari a 0 minuti non vengono conteggiati."
    )

    render_estimate_detail_table(estimate_df)

    st.divider()

    st.subheader("Andamento mensile tempi medi per Epic")

    monthly_summary_df = build_monthly_resolution_summary_by_epic(calculated_df)

    if monthly_summary_df.empty:
        st.info(
            "Nessun ticket calcolato con data fine lavorazione da giugno ad oggi."
        )
    else:
        st.caption(
            "Il grafico mostra come cambia il **tempo medio netto di risoluzione** "
            "mese per mese, separando i valori per **Epic**. "
            "I giorni sono giorni lavorativi equivalenti da 8 ore."
        )

        fig = px.line(
            monthly_summary_df,
            x="Mese",
            y="Tempo medio netto giorni",
            color="Epic",
            markers=True,
            text="Tempo medio netto giorni",
            title="Andamento mensile del tempo medio di risoluzione per Epic",
        )

        fig.update_layout(
            xaxis_title="Mese chiusura",
            yaxis_title="Tempo medio netto giorni lav.",
            legend_title="Epic",
        )

        fig.update_traces(
            marker=dict(size=9),
            textposition="top center",
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
            key="resolution_time_monthly_trend_by_epic_chart",
        )

        st.dataframe(
            monthly_summary_df,
            use_container_width=True,
            hide_index=True,
            key="resolution_time_monthly_summary_by_epic_table",
            column_config={
                "Tempo medio netto giorni": st.column_config.NumberColumn(
                    "Tempo medio netto giorni lav.",
                    format="%.2f",
                ),
                "Tempo mediano netto giorni": st.column_config.NumberColumn(
                    "Tempo mediano netto giorni lav.",
                    format="%.2f",
                ),
                "Tempo massimo netto giorni": st.column_config.NumberColumn(
                    "Tempo massimo netto giorni lav.",
                    format="%.2f",
                ),
                "Tempo medio netto ore": st.column_config.NumberColumn(
                    "Tempo medio netto ore",
                    format="%.2f",
                ),
                "Tempo escluso medio giorni": st.column_config.NumberColumn(
                    "Tempo escluso medio giorni lav.",
                    format="%.2f",
                ),
            },
        )

    st.divider()

    st.subheader("Tempi medi per Epic")

    if calculated_df.empty:
        st.info("Nessun ticket calcolato disponibile per il confronto per Epic.")
    else:
        epic_summary_df = build_epic_resolution_summary(
            calculated_df=calculated_df,
            estimate_source_df=completed_issue_df,
        )

        st.caption(
            "Questa tabella permette di confrontare il tempo medio di risoluzione "
            "tra le diverse Epic e include anche il rispetto delle stime, "
            "calcolato su tempo stimato e tempo impiegato Jira."
        )

        st.dataframe(
            epic_summary_df,
            use_container_width=True,
            hide_index=True,
            key="resolution_time_epic_summary_table",
            column_config={
                "% entro stima": st.column_config.NumberColumn(
                    "% entro stima",
                    format="%.1f%%",
                ),
                "Tempo medio netto giorni": st.column_config.NumberColumn(
                    "Tempo medio netto giorni lav.",
                    format="%.2f",
                ),
                "Tempo mediano netto giorni": st.column_config.NumberColumn(
                    "Tempo mediano netto giorni lav.",
                    format="%.2f",
                ),
                "Tempo massimo netto giorni": st.column_config.NumberColumn(
                    "Tempo massimo netto giorni lav.",
                    format="%.2f",
                ),
                "Tempo medio netto ore": st.column_config.NumberColumn(
                    "Tempo medio netto ore",
                    format="%.2f",
                ),
                "Tempo impiegato medio ore": st.column_config.NumberColumn(
                    "Tempo impiegato medio ore",
                    format="%.2f",
                ),
                "Tempo escluso medio giorni": st.column_config.NumberColumn(
                    "Tempo escluso medio giorni lav.",
                    format="%.2f",
                ),
            },
        )

    st.divider()

    st.subheader("Esiti calcolo")

    esiti_df = (
        resolution_df
        .groupby("Esito", dropna=False)
        .size()
        .reset_index(name="Ticket")
        .sort_values("Ticket", ascending=False)
    )

    st.dataframe(
        esiti_df,
        use_container_width=True,
        hide_index=True,
        key="resolution_time_esiti_table",
    )

    st.divider()

    st.subheader("Dettaglio tempi ticket per ticket")

    detail_df = resolution_df.copy()

    if "Data inizio lavorazione" in detail_df.columns:
        detail_df["Data inizio lavorazione"] = pd.to_datetime(
            detail_df["Data inizio lavorazione"],
            errors="coerce",
        ).dt.strftime("%d/%m/%Y %H:%M")

    if "Data fine lavorazione" in detail_df.columns:
        detail_df["Data fine lavorazione"] = pd.to_datetime(
            detail_df["Data fine lavorazione"],
            errors="coerce",
        ).dt.strftime("%d/%m/%Y %H:%M")

    columns = [
        "Issue",
        "Summary",
        "IssueType",
        "Stato corrente",
        "Assignee",
        "EpicKey",
        "EpicName",
        "Epic",
        "StimaOre",
        "Tempo impiegato ore",
        "Data inizio lavorazione",
        "Data fine lavorazione",
        "Stato fine",
        "Tempo lordo giorni",
        "Tempo escluso giorni",
        "Tempo netto giorni",
        "Tempo netto ore",
        "Entro stima",
        "Scostamento ore",
        "Esito",
        "Url",
    ]

    existing_columns = [
        column
        for column in columns
        if column in detail_df.columns
    ]

    st.caption(
        "Le colonne in giorni rappresentano giorni lavorativi equivalenti "
        f"da {WORKING_HOURS_PER_DAY} ore. "
        "Il rispetto stime confronta invece **Tempo impiegato ore** e **StimaOre**."
    )

    st.dataframe(
        detail_df[existing_columns],
        use_container_width=True,
        hide_index=True,
        key="resolution_time_detail_table",
        column_config={
            "StimaOre": st.column_config.NumberColumn(
                "Tempo stimato ore",
                format="%.2f",
            ),
            "Tempo impiegato ore": st.column_config.NumberColumn(
                "Tempo impiegato ore",
                format="%.2f",
            ),
            "Tempo lordo giorni": st.column_config.NumberColumn(
                "Tempo lordo giorni lav.",
                format="%.2f",
            ),
            "Tempo escluso giorni": st.column_config.NumberColumn(
                "Tempo escluso giorni lav.",
                format="%.2f",
            ),
            "Tempo netto giorni": st.column_config.NumberColumn(
                "Tempo netto giorni lav.",
                format="%.2f",
            ),
            "Tempo netto ore": st.column_config.NumberColumn(
                "Tempo netto ore",
                format="%.2f",
            ),
            "Scostamento ore": st.column_config.NumberColumn(
                "Scostamento ore",
                format="%.2f",
            ),
            "Url": st.column_config.LinkColumn("Jira"),
        },
    )

    excel_file = create_resolution_time_excel_export(
        resolution_df=resolution_df,
        estimate_df=estimate_df,
    )

    st.download_button(
        label="📥 Scarica Excel tempi risoluzione",
        data=excel_file,
        file_name="jira_tempi_risoluzione.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_resolution_time_excel",
    )

def render_estimate_compliance_cards(estimate_summary: dict):
    e1, e2, e3, e4 = st.columns(4)

    with e1:
        render_metric_card(
            label="Ticket con stima valorizzata",
            value=estimate_summary["ticket_con_stima"],
            color="#2563EB",
            background="#EFF6FF",
        )

    with e2:
        render_metric_card(
            label="Chiusi entro stima",
            value=estimate_summary["entro_stima"],
            color="#027A48",
            background="#ECFDF3",
        )

    with e3:
        render_metric_card(
            label="Sforati",
            value=estimate_summary["sforati"],
            color="#B42318",
            background="#FEF3F2",
        )

    with e4:
        render_metric_card(
            label="% entro stima",
            value=f"{estimate_summary['percentuale_entro_stima']}%",
            color="#027A48",
            background="#ECFDF3",
        )

def render_estimate_detail_table(estimate_df: pd.DataFrame):
    with st.expander("Dettaglio rispetto stime", expanded=False):
        if estimate_df.empty:
            st.info(
                "Nessun ticket con tempo stimato valorizzato. "
                "I ticket con stima nulla o pari a 0 minuti sono esclusi."
            )
            return

        st.dataframe(
            estimate_df,
            use_container_width=True,
            hide_index=True,
            key="estimate_compliance_detail_table",
            column_config={
                "StimaOre": st.column_config.NumberColumn(
                    "Tempo stimato ore",
                    format="%.2f",
                ),
                "Tempo impiegato ore": st.column_config.NumberColumn(
                    "Tempo impiegato ore",
                    format="%.2f",
                ),
                "Scostamento ore": st.column_config.NumberColumn(
                    "Scostamento ore",
                    format="%.2f",
                ),
                "Url": st.column_config.LinkColumn("Jira"),
            },
        )
