import io
import re
import unicodedata
import requests
import pandas as pd
import streamlit as st

from requests.auth import HTTPBasicAuth

# ======================
# CONFIG ISSUE TYPE
# ======================

TASK_BUG_TYPES = {
    "TASK",
    "BUG",
}

# ======================
# CONFIG STATI
# ======================

OPENING_STATUSES = {
    "DA FARE",
    "TO DO",
    "TODO",
    "BACKLOG",
    "APERTO",
    "APERTA",
    "OPEN",
    "NEW",
    "NUOVO",
    "NUOVA",
}

EXECUTION_STATUSES = {
    "ANALISI",
    "ANALISI PRELIMINARE",
    "IN CORSO",
    "IN PROGRESS",
    "IN LAVORAZIONE",
    "LAVORAZIONE",
    "SVILUPPO",
    "DEVELOPMENT",
    "IMPLEMENTAZIONE",
    "IN IMPLEMENTAZIONE",
    "TEST",
    "IN TEST",
    "REVIEW",
    "IN REVIEW",
    "VALIDAZIONE",
    "IN VALIDAZIONE",
}

EXCLUDED_STATUSES = {
    "ON HOLD TEMP",
    "BLOCCATO",
}

CLOSING_STATUSES = {
    "DONE",
    "CHIUSO",
    "CHIUSA",
    "CLOSED",
    "RESOLVED",
    "RISOLTO",
    "RISOLTA",
    "COMPLETATO",
    "COMPLETATA",
    "COMPLETED",
    "RILASCIATO",
    "RILASCIATA",
    "RELEASED",
    "ANNULLATO",
    "ANNULLATA",
    "CANCELLED",
    "CANCELED",
    "SCARTATO",
    "SCARTATA",
}

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

def is_task_or_bug(issue_type) -> bool:
    return normalize_issue_type(issue_type) in TASK_BUG_TYPES

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

    return False

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

        if (
            from_status in OPENING_STATUSES
            and to_status in EXECUTION_STATUSES
        ):
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
# CALCOLO TEMPI
# ======================

def compute_resolution_time_for_issue(
    issue_info: dict,
    changelog: list[dict],
) -> dict:
    issue_key = issue_info.get("Issue", "")

    result = {
        "Issue": issue_key,
        "Summary": issue_info.get("Summary", ""),
        "IssueType": issue_info.get("IssueType", ""),
        "Stato corrente": issue_info.get("Stato", ""),
        "Assignee": issue_info.get("Assignee", ""),
        "EpicKey": issue_info.get("EpicKey", ""),
        "EpicName": issue_info.get("EpicName", ""),
        "Data inizio lavorazione": pd.NaT,
        "Data fine lavorazione": pd.NaT,
        "Stato fine": "",
        "Tempo lordo giorni": None,
        "Tempo lordo ore": None,
        "Tempo escluso giorni": None,
        "Tempo escluso ore": None,
        "Tempo netto giorni": None,
        "Tempo netto ore": None,
        "Esito": "",
        "Url": issue_info.get("Url", ""),
    }

    if not is_task_or_bug(issue_info.get("IssueType", "")):
        result["Esito"] = "Escluso: issue type non Task/Bug"
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

    result["Tempo lordo ore"] = round(gross_seconds / 3600, 2)
    result["Tempo lordo giorni"] = round(gross_seconds / 86400, 2)

    result["Tempo escluso ore"] = round(excluded_seconds / 3600, 2)
    result["Tempo escluso giorni"] = round(excluded_seconds / 86400, 2)

    result["Tempo netto ore"] = round(net_seconds / 3600, 2)
    result["Tempo netto giorni"] = round(net_seconds / 86400, 2)

    if end_source == "resolutiondate":
        result["Esito"] = "Calcolato tramite resolutiondate"
    else:
        result["Esito"] = "Calcolato"

    return result

def filter_completed_task_bug_issues(issue_df: pd.DataFrame) -> pd.DataFrame:
    if issue_df.empty:
        return issue_df.copy()

    filtered_df = issue_df.copy()

    filtered_df = filtered_df[
        filtered_df["IssueType"].apply(is_task_or_bug)
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
        "Data inizio lavorazione",
        "Data fine lavorazione",
        "Stato fine",
        "Tempo lordo giorni",
        "Tempo lordo ore",
        "Tempo escluso giorni",
        "Tempo escluso ore",
        "Tempo netto giorni",
        "Tempo netto ore",
        "Esito",
        "Url",
    ]

    if issue_df.empty:
        return pd.DataFrame(columns=columns)

    completed_task_bug_df = filter_completed_task_bug_issues(issue_df)

    if completed_task_bug_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    issue_records = completed_task_bug_df.to_dict(orient="records")
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
                "Data inizio lavorazione": pd.NaT,
                "Data fine lavorazione": pd.NaT,
                "Stato fine": "",
                "Tempo lordo giorni": None,
                "Tempo lordo ore": None,
                "Tempo escluso giorni": None,
                "Tempo escluso ore": None,
                "Tempo netto giorni": None,
                "Tempo netto ore": None,
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

    result_df["Data inizio lavorazione"] = pd.to_datetime(
        result_df["Data inizio lavorazione"],
        errors="coerce",
    )

    result_df["Data fine lavorazione"] = pd.to_datetime(
        result_df["Data fine lavorazione"],
        errors="coerce",
    )

    numeric_columns = [
        "Tempo lordo giorni",
        "Tempo lordo ore",
        "Tempo escluso giorni",
        "Tempo escluso ore",
        "Tempo netto giorni",
        "Tempo netto ore",
    ]

    for column in numeric_columns:
        result_df[column] = pd.to_numeric(
            result_df[column],
            errors="coerce",
        )

    return result_df

# ======================
# EXPORT
# ======================

def create_resolution_time_excel_export(resolution_df: pd.DataFrame):
    output = io.BytesIO()

    export_df = resolution_df.copy()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        export_df.to_excel(
            writer,
            index=False,
            sheet_name="Tempi risoluzione",
        )

        workbook = writer.book
        worksheet = writer.sheets["Tempi risoluzione"]

        datetime_format = workbook.add_format(
            {
                "num_format": "dd/mm/yyyy hh:mm",
            }
        )

        number_format = workbook.add_format(
            {
                "num_format": "0.00",
            }
        )

        worksheet.set_column("A:A", 14)
        worksheet.set_column("B:B", 60)
        worksheet.set_column("C:E", 18)
        worksheet.set_column("F:G", 26)
        worksheet.set_column("H:I", 22, datetime_format)
        worksheet.set_column("J:J", 18)
        worksheet.set_column("K:P", 18, number_format)
        worksheet.set_column("Q:Q", 46)
        worksheet.set_column("R:R", 60)

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
        "Il tempo viene calcolato solo sui **Task/Bug completati**. "
        "Il calcolo parte dalla prima transizione da uno stato di apertura "
        "a uno stato di esecuzione, ad esempio **Da fare → ANALISI** oppure "
        "**Da fare → IN CORSO**. "
        "Il tempo trascorso negli stati **ON HOLD TEMP** e **BLOCCATO** "
        "viene escluso dal calcolo netto."
    )

    if issue_df.empty:
        st.info("Nessuna issue disponibile per i filtri selezionati.")
        return

    completed_task_bug_df = filter_completed_task_bug_issues(issue_df)

    if completed_task_bug_df.empty:
        st.info(
            "Nessun Task/Bug completato disponibile per il calcolo "
            "dei tempi di risoluzione."
        )
        return

    total_visible_issues = len(issue_df)
    total_completed_task_bug = len(completed_task_bug_df)

    st.caption(
        f"Ticket nel perimetro filtrato: **{total_visible_issues}** · "
        f"Task/Bug completati analizzati: **{total_completed_task_bug}**"
    )

    issue_signature = "|".join(
        sorted(
            completed_task_bug_df["Issue"]
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
            issue_df=completed_task_bug_df,
            jira_domain=jira_domain,
            jira_email=jira_email,
            jira_api_token=jira_api_token,
        )

        st.session_state["resolution_time_df"] = resolution_df

    if not st.session_state.get("resolution_time_loaded", False):
        st.info(
            "Premi **Calcola / aggiorna tempi di risoluzione** per recuperare "
            "la changelog Jira solo dei Task/Bug completati e calcolare i tempi."
        )
        return

    resolution_df = st.session_state.get("resolution_time_df")

    if resolution_df is None or resolution_df.empty:
        st.info("Nessun tempo di risoluzione disponibile.")
        return

    calculated_df = resolution_df[
        resolution_df["Esito"].isin(
            [
                "Calcolato",
                "Calcolato tramite resolutiondate",
            ]
        )
    ].copy()

    total_rows = len(resolution_df)
    calculated_tickets = len(calculated_df)
    not_calculated_tickets = total_rows - calculated_tickets

    average_days = 0
    average_hours = 0
    median_days = 0

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

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Tempo medio risoluzione", f"{average_days} giorni")
    c2.metric("Tempo medio risoluzione ore", f"{average_hours} ore")
    c3.metric("Ticket calcolati", calculated_tickets)
    c4.metric("Ticket non calcolati", max(not_calculated_tickets, 0))

    c5, c6, c7, c8 = st.columns(4)

    c5.metric("Mediana risoluzione", f"{median_days} giorni")
    c6.metric("Task/Bug completati analizzati", total_rows)

    if not calculated_df.empty:
        c7.metric(
            "Tempo massimo netto",
            f"{round(calculated_df['Tempo netto giorni'].max(), 2)} giorni",
        )

        c8.metric(
            "Tempo escluso medio",
            f"{round(calculated_df['Tempo escluso giorni'].mean(), 2)} giorni",
        )
    else:
        c7.metric("Tempo massimo netto", "0 giorni")
        c8.metric("Tempo escluso medio", "0 giorni")

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

    st.subheader("Dettaglio tempi task per task")

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
        "Data inizio lavorazione",
        "Data fine lavorazione",
        "Stato fine",
        "Tempo lordo giorni",
        "Tempo escluso giorni",
        "Tempo netto giorni",
        "Tempo netto ore",
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
        key="resolution_time_detail_table",
        column_config={
            "Tempo lordo giorni": st.column_config.NumberColumn(
                "Tempo lordo giorni",
                format="%.2f",
            ),
            "Tempo escluso giorni": st.column_config.NumberColumn(
                "Tempo escluso giorni",
                format="%.2f",
            ),
            "Tempo netto giorni": st.column_config.NumberColumn(
                "Tempo netto giorni",
                format="%.2f",
            ),
            "Tempo netto ore": st.column_config.NumberColumn(
                "Tempo netto ore",
                format="%.2f",
            ),
            "Url": st.column_config.LinkColumn("Jira"),
        },
    )

    excel_file = create_resolution_time_excel_export(resolution_df)

    st.download_button(
        label="📥 Scarica Excel tempi risoluzione",
        data=excel_file,
        file_name="jira_tempi_risoluzione.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_resolution_time_excel",
    )
