import html
import re
import unicodedata

import pandas as pd
import plotly.express as px
import streamlit as st

# ======================
# CONFIG
# ======================

TASK_BUG_TYPES = {
    "task",
    "bug",
}

ALLOWED_EPIC_NAMES = {
    "AM",
    "GESTIONE MEMORIA",
}

DONE_STATUSES = {
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
    "FATTO",
    "VERBALE CHIUSO",
    "TICKET FIL NON CHIUSO",
    "ANNULLATO",
    "ANNULLATA",
    "CANCELLED",
    "CANCELED",
}

NO_PRIORITY_LABEL = "Nessuna priorità cliente"

PRIORITY_ORDER = [
    "Altissima",
    "Alta",
    "Media",
    "Bassa",
    "Fase 2",
    NO_PRIORITY_LABEL,
]

PRIORITY_COLOR_MAP = {
    "Altissima": "#DC2626",
    "Alta": "#F97316",
    "Media": "#FACC15",
    "Bassa": "#22C55E",
    "Fase 2": "#7DD3FC",
    NO_PRIORITY_LABEL: "#94A3B8",
    "Altro": "#64748B",
}

ITALIAN_MONTH_NAMES = {
    1: "Gennaio",
    2: "Febbraio",
    3: "Marzo",
    4: "Aprile",
    5: "Maggio",
    6: "Giugno",
    7: "Luglio",
    8: "Agosto",
    9: "Settembre",
    10: "Ottobre",
    11: "Novembre",
    12: "Dicembre",
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

def filter_task_bug(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "IssueType" not in df.columns:
        return df.copy()

    return df[
        df["IssueType"]
        .apply(normalize_issue_type)
        .isin(TASK_BUG_TYPES)
    ].copy()

def is_done_issue(row: dict) -> bool:
    done_value = row.get("Done", False)

    if bool(done_value) is True:
        return True

    status_category = normalize_status(row.get("StatusCategory", ""))
    status = normalize_status(row.get("Stato", ""))

    if status_category == "DONE":
        return True

    if status in DONE_STATUSES:
        return True

    return False

def get_priority_label(row: dict) -> str:
    priority = row.get("Priority", "")

    if priority is None or str(priority).strip() == "":
        priority = row.get("Priorità cliente", "")

    if priority is None or str(priority).strip() == "":
        return NO_PRIORITY_LABEL

    return str(priority).strip()

def get_priority_order(priority) -> int:
    normalized_priority = normalize_priority_for_match(priority)

    for index, priority_value in enumerate(PRIORITY_ORDER):
        if normalized_priority == priority_value.lower():
            return index

    return 999

def get_priority_color_key(priority):
    normalized_priority = normalize_priority_for_match(priority)

    for priority_value in PRIORITY_COLOR_MAP.keys():
        if normalized_priority == priority_value.lower():
            return priority_value

    return "Altro"

# ======================
# DATE HELPERS
# ======================

def get_closed_timestamp(row: dict):
    possible_columns = [
        "ResolutionDate",
        "Data risoluzione",
        "resolutiondate",
    ]

    for column in possible_columns:
        if column not in row:
            continue

        value = row.get(column)

        if value is None or value == "":
            continue

        parsed_value = pd.to_datetime(
            value,
            errors="coerce",
        )

        if not pd.isna(parsed_value):
            return parsed_value

    updated_value = row.get("Updated", None)

    if updated_value is None or updated_value == "":
        return pd.NaT

    return pd.to_datetime(
        updated_value,
        errors="coerce",
    )

def get_month_label(timestamp, include_year=False):
    if pd.isna(timestamp):
        return ""

    month_name = ITALIAN_MONTH_NAMES.get(timestamp.month, str(timestamp.month))

    if include_year:
        return f"{month_name} {timestamp.year}"

    return month_name

def get_week_label(timestamp):
    if pd.isna(timestamp):
        return ""

    iso_calendar = timestamp.isocalendar()
    year = int(iso_calendar.year)
    week = int(iso_calendar.week)

    return f"{year} - Settimana {week:02d}"

def get_week_key(timestamp):
    if pd.isna(timestamp):
        return ""

    iso_calendar = timestamp.isocalendar()
    year = int(iso_calendar.year)
    week = int(iso_calendar.week)

    return f"{year}-W{week:02d}"

# ======================
# DATASET
# ======================

def build_closed_ticket_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Issue",
        "Summary",
        "Assignee",
        "Priorità cliente",
        "Data chiusura",
        "MeseKey",
        "Mese",
        "SettimanaKey",
        "Settimana",
        "Url",
    ]

    if df.empty:
        return pd.DataFrame(columns=columns)

    scoped_df = filter_allowed_epics(df)

    if scoped_df.empty:
        return pd.DataFrame(columns=columns)

    task_bug_df = filter_task_bug(scoped_df)

    if task_bug_df.empty:
        return pd.DataFrame(columns=columns)

    closed_df = task_bug_df[
        task_bug_df.apply(
            lambda row: is_done_issue(row.to_dict()),
            axis=1,
        )
    ].copy()

    if closed_df.empty:
        return pd.DataFrame(columns=columns)

    closed_df["Data chiusura"] = closed_df.apply(
        lambda row: get_closed_timestamp(row.to_dict()),
        axis=1,
    )

    closed_df["Data chiusura"] = pd.to_datetime(
        closed_df["Data chiusura"],
        errors="coerce",
    )

    closed_df = closed_df.dropna(subset=["Data chiusura"])

    if closed_df.empty:
        return pd.DataFrame(columns=columns)

    years = closed_df["Data chiusura"].dt.year.dropna().unique()
    include_year = len(years) > 1

    closed_df["Priorità cliente"] = closed_df.apply(
        lambda row: get_priority_label(row.to_dict()),
        axis=1,
    )

    closed_df["MeseKey"] = (
        closed_df["Data chiusura"]
        .dt.to_period("M")
        .astype(str)
    )

    closed_df["Mese"] = closed_df["Data chiusura"].apply(
        lambda value: get_month_label(value, include_year=include_year)
    )

    closed_df["SettimanaKey"] = closed_df["Data chiusura"].apply(get_week_key)
    closed_df["Settimana"] = closed_df["Data chiusura"].apply(get_week_label)

    result_df = closed_df.copy()

    if "Assignee" not in result_df.columns:
        result_df["Assignee"] = ""

    result_df["Assignee"] = (
        result_df["Assignee"]
        .fillna("")
        .replace("", "Non assegnato")
    )

    for column in columns:
        if column not in result_df.columns:
            result_df[column] = ""

    return result_df[columns].copy()

# ======================
# AGGREGAZIONI
# ======================

def build_weekly_summary(closed_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "SettimanaKey",
        "Settimana",
        "Ticket risolti",
    ]

    if closed_df.empty:
        return pd.DataFrame(columns=columns)

    summary_df = (
        closed_df
        .groupby(["SettimanaKey", "Settimana"], dropna=False)
        .size()
        .reset_index(name="Ticket risolti")
        .sort_values("SettimanaKey")
    )

    return summary_df[columns]

def build_monthly_summary(closed_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "MeseKey",
        "Mese",
        "Ticket risolti",
    ]

    if closed_df.empty:
        return pd.DataFrame(columns=columns)

    summary_df = (
        closed_df
        .groupby(["MeseKey", "Mese"], dropna=False)
        .size()
        .reset_index(name="Ticket risolti")
        .sort_values("MeseKey")
    )

    return summary_df[columns]

def build_weekly_priority_summary(closed_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "SettimanaKey",
        "Settimana",
        "Priorità cliente",
        "Ticket risolti",
    ]

    if closed_df.empty:
        return pd.DataFrame(columns=columns)

    summary_df = (
        closed_df
        .groupby(["SettimanaKey", "Settimana", "Priorità cliente"], dropna=False)
        .size()
        .reset_index(name="Ticket risolti")
    )

    summary_df["__priority_order"] = summary_df["Priorità cliente"].apply(
        get_priority_order
    )

    summary_df = (
        summary_df
        .sort_values(["SettimanaKey", "__priority_order", "Priorità cliente"])
        .drop(columns=["__priority_order"])
        .reset_index(drop=True)
    )

    return summary_df[columns]

def build_monthly_priority_summary(closed_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "MeseKey",
        "Mese",
        "Priorità cliente",
        "Ticket risolti",
    ]

    if closed_df.empty:
        return pd.DataFrame(columns=columns)

    summary_df = (
        closed_df
        .groupby(["MeseKey", "Mese", "Priorità cliente"], dropna=False)
        .size()
        .reset_index(name="Ticket risolti")
    )

    summary_df["__priority_order"] = summary_df["Priorità cliente"].apply(
        get_priority_order
    )

    summary_df = (
        summary_df
        .sort_values(["MeseKey", "__priority_order", "Priorità cliente"])
        .drop(columns=["__priority_order"])
        .reset_index(drop=True)
    )

    return summary_df[columns]

def get_priority_order_list(df: pd.DataFrame):
    if df.empty or "Priorità cliente" not in df.columns:
        return []

    available_priorities = df["Priorità cliente"].dropna().unique().tolist()

    ordered_priorities = [
        priority
        for priority in PRIORITY_ORDER
        if priority in available_priorities
    ]

    remaining_priorities = sorted(
        [
            priority
            for priority in available_priorities
            if priority not in ordered_priorities
        ]
    )

    return ordered_priorities + remaining_priorities

# ======================
# CHARTS
# ======================

def render_weekly_chart(weekly_df: pd.DataFrame):
    if weekly_df.empty:
        st.info("Nessun ticket risolto disponibile per il riepilogo settimanale.")
        return

    ordered_weeks = weekly_df["Settimana"].tolist()

    fig = px.bar(
        weekly_df,
        x="Settimana",
        y="Ticket risolti",
        text="Ticket risolti",
        title="Ticket risolti per settimana",
        color_discrete_sequence=["#2563EB"],
    )

    fig.update_layout(
        xaxis_title="Settimana",
        yaxis_title="Numero ticket risolti",
        showlegend=False,
    )

    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=ordered_weeks,
    )

    fig.update_traces(
        textposition="outside",
        marker_line_width=0,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key="resolution_count_weekly_chart",
    )

def render_monthly_chart(monthly_df: pd.DataFrame):
    if monthly_df.empty:
        st.info("Nessun ticket risolto disponibile per il riepilogo mensile.")
        return

    ordered_months = monthly_df["Mese"].tolist()

    fig = px.bar(
        monthly_df,
        x="Mese",
        y="Ticket risolti",
        text="Ticket risolti",
        title="Ticket risolti per mese",
        color_discrete_sequence=["#16A34A"],
    )

    fig.update_layout(
        xaxis_title="Mese",
        yaxis_title="Numero ticket risolti",
        showlegend=False,
    )

    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=ordered_months,
    )

    fig.update_traces(
        textposition="outside",
        marker_line_width=0,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key="resolution_count_monthly_chart",
    )

def render_weekly_priority_chart(weekly_priority_df: pd.DataFrame):
    if weekly_priority_df.empty:
        st.info(
            "Nessun ticket risolto disponibile per il riepilogo settimanale "
            "per priorità."
        )
        return

    ordered_weeks = (
        weekly_priority_df[["SettimanaKey", "Settimana"]]
        .drop_duplicates()
        .sort_values("SettimanaKey")["Settimana"]
        .tolist()
    )

    ordered_priorities = get_priority_order_list(weekly_priority_df)

    fig = px.bar(
        weekly_priority_df,
        x="Settimana",
        y="Ticket risolti",
        color="Priorità cliente",
        text="Ticket risolti",
        title="Ticket risolti per settimana e priorità cliente",
        color_discrete_map=PRIORITY_COLOR_MAP,
        category_orders={
            "Settimana": ordered_weeks,
            "Priorità cliente": ordered_priorities,
        },
    )

    fig.update_layout(
        xaxis_title="Settimana",
        yaxis_title="Numero ticket risolti",
        legend_title="Priorità cliente",
        barmode="stack",
    )

    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=ordered_weeks,
    )

    fig.update_traces(
        textposition="inside",
        marker_line_width=0,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key="resolution_count_weekly_priority_chart",
    )

def render_monthly_priority_chart(monthly_priority_df: pd.DataFrame):
    if monthly_priority_df.empty:
        st.info(
            "Nessun ticket risolto disponibile per il riepilogo mensile "
            "per priorità."
        )
        return

    ordered_months = (
        monthly_priority_df[["MeseKey", "Mese"]]
        .drop_duplicates()
        .sort_values("MeseKey")["Mese"]
        .tolist()
    )

    ordered_priorities = get_priority_order_list(monthly_priority_df)

    fig = px.bar(
        monthly_priority_df,
        x="Mese",
        y="Ticket risolti",
        color="Priorità cliente",
        text="Ticket risolti",
        title="Ticket risolti per mese e priorità cliente",
        color_discrete_map=PRIORITY_COLOR_MAP,
        category_orders={
            "Mese": ordered_months,
            "Priorità cliente": ordered_priorities,
        },
    )

    fig.update_layout(
        xaxis_title="Mese",
        yaxis_title="Numero ticket risolti",
        legend_title="Priorità cliente",
        barmode="stack",
    )

    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=ordered_months,
    )

    fig.update_traces(
        textposition="inside",
        marker_line_width=0,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key="resolution_count_monthly_priority_chart",
    )

# ======================
# UI
# ======================

def render_resolution_count_section(df: pd.DataFrame):
    st.subheader("Numero risoluzione")

    st.caption(
        "La sezione mostra il numero di **Task/Bug risolti** per settimana "
        "e per mese, sia come totale sia suddivisi per **priorità cliente**. "
        "Sono considerati solo i ticket appartenenti alle Epic **AM** e "
        "**Gestione Memoria**."
    )

    if df.empty:
        st.info("Nessun dato disponibile per i filtri selezionati.")
        return

    closed_df = build_closed_ticket_dataframe(df)

    if closed_df.empty:
        st.info(
            "Nessun Task/Bug risolto disponibile nel perimetro selezionato."
        )
        return

    weekly_df = build_weekly_summary(closed_df)
    monthly_df = build_monthly_summary(closed_df)
    weekly_priority_df = build_weekly_priority_summary(closed_df)
    monthly_priority_df = build_monthly_priority_summary(closed_df)

    total_closed = len(closed_df)
    weeks_count = weekly_df["Settimana"].nunique() if not weekly_df.empty else 0
    months_count = monthly_df["Mese"].nunique() if not monthly_df.empty else 0

    average_weekly = 0
    average_monthly = 0

    if weeks_count > 0:
        average_weekly = round(total_closed / weeks_count, 1)

    if months_count > 0:
        average_monthly = round(total_closed / months_count, 1)

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        render_metric_card(
            label="Ticket risolti",
            value=total_closed,
            color="#027A48",
            background="#ECFDF3",
        )

    with c2:
        render_metric_card(
            label="Settimane con risoluzioni",
            value=weeks_count,
            color="#2563EB",
            background="#EFF6FF",
        )

    with c3:
        render_metric_card(
            label="Media risolti / settimana",
            value=average_weekly,
            color="#2563EB",
            background="#EFF6FF",
        )

    with c4:
        render_metric_card(
            label="Media risolti / mese",
            value=average_monthly,
            color="#16A34A",
            background="#ECFDF3",
        )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        render_weekly_chart(weekly_df)

        st.dataframe(
            weekly_df.drop(columns=["SettimanaKey"]),
            use_container_width=True,
            hide_index=True,
            key="resolution_count_weekly_table",
        )

    with col2:
        render_monthly_chart(monthly_df)

        st.dataframe(
            monthly_df.drop(columns=["MeseKey"]),
            use_container_width=True,
            hide_index=True,
            key="resolution_count_monthly_table",
        )

    st.divider()

    st.subheader("Risoluzioni per priorità cliente")

    render_weekly_priority_chart(weekly_priority_df)

    weekly_priority_table_df = weekly_priority_df.drop(columns=["SettimanaKey"])

    st.dataframe(
        weekly_priority_table_df,
        use_container_width=True,
        hide_index=True,
        key="resolution_count_weekly_priority_table",
    )

    st.divider()

    render_monthly_priority_chart(monthly_priority_df)

    monthly_priority_table_df = monthly_priority_df.drop(columns=["MeseKey"])

    st.dataframe(
        monthly_priority_table_df,
        use_container_width=True,
        hide_index=True,
        key="resolution_count_monthly_priority_table",
    )

    st.divider()

    st.subheader("Dettaglio ticket risolti")

    detail_df = closed_df.copy()

    detail_df["Data chiusura"] = pd.to_datetime(
        detail_df["Data chiusura"],
        errors="coerce",
    ).dt.strftime("%d/%m/%Y %H:%M")

    detail_columns = [
        "Issue",
        "Summary",
        "Assignee",
        "Priorità cliente",
        "Data chiusura",
        "Settimana",
        "Mese",
        "Url",
    ]

    existing_columns = [
        column
        for column in detail_columns
        if column in detail_df.columns
    ]

    st.dataframe(
        detail_df[existing_columns],
        use_container_width=True,
        hide_index=True,
        key="resolution_count_detail_table",
        column_config={
            "Url": st.column_config.LinkColumn("Jira"),
        },
    )
