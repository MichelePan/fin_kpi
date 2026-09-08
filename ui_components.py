import html
import pandas as pd
import plotly.express as px
import streamlit as st

TASK_BUG_TYPES = {
    "task",
    "bug",
}

STATUS_ORDER = [
    "Da fare",
    "Analisi",
    "In corso",
    "ON HOLD TEMP",
    "In revisione/Test",
    "BLOCCATO",
    "ANNULLATO",
    "TICKET FIL NON CHIUSO",
    "Verbale Chiuso",
]

STATUS_ORDER_MAP = {
    status.strip().upper(): index
    for index, status in enumerate(STATUS_ORDER)
}

STATUS_COLOR_GROUPS = {
    "DA FARE": "Da fare",
    "ANALISI": "In corso",
    "IN CORSO": "In corso",
    "ON HOLD TEMP": "In corso",
    "IN REVISIONE/TEST": "In corso",
    "BLOCCATO": "In corso",
    "ANNULLATO": "Completato",
    "TICKET FIL NON CHIUSO": "Completato",
    "VERBALE CHIUSO": "Completato",
    "FATTO": "Completato",
    "DONE": "Completato",
    "CHIUSO": "Completato",
}

STATUS_COLOR_MAP = {
    "Da fare": "#7DD3FC",
    "In corso": "#2563EB",
    "Completato": "#16A34A",
    "Altro": "#94A3B8",
}

PEOPLE_STATUS_COLOR_MAP = {
    "Aperti": "#7DD3FC",
    "Completati": "#2563EB",
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
    "Altro": "#94A3B8",
}

PRIORITY_COMPLEXITY_SCORE = {
    "Altissima": 5,
    "Alta": 4,
    "Media": 3,
    "Bassa": 2,
    "Fase 2": 1,
    NO_PRIORITY_LABEL: 0,
    "Altro": 0,
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

def normalize_issue_type(value):
    if value is None:
        return ""

    return str(value).strip().lower()

def normalize_status(value):
    if value is None:
        return ""

    return str(value).strip().upper()

def normalize_priority(value):
    if value is None:
        return ""

    return str(value).strip()

def get_status_sort_order(status):
    normalized_status = normalize_status(status)

    return STATUS_ORDER_MAP.get(normalized_status, 999)

def get_status_color_group(status):
    normalized_status = normalize_status(status)

    return STATUS_COLOR_GROUPS.get(normalized_status, "Altro")

def get_priority_sort_order(priority):
    normalized_priority = normalize_priority(priority)

    if normalized_priority.lower() == NO_PRIORITY_LABEL.lower():
        return 9999

    for index, priority_value in enumerate(PRIORITY_ORDER):
        if normalized_priority.lower() == priority_value.lower():
            return index

    return 999

def get_priority_color_key(priority):
    normalized_priority = normalize_priority(priority)

    for priority_value in PRIORITY_COLOR_MAP.keys():
        if normalized_priority.lower() == priority_value.lower():
            return priority_value

    return "Altro"

def get_priority_complexity_score(priority):
    color_key = get_priority_color_key(priority)

    return PRIORITY_COMPLEXITY_SCORE.get(color_key, 0)

def get_month_label(timestamp, include_year=False):
    if pd.isna(timestamp):
        return ""

    month_name = ITALIAN_MONTH_NAMES.get(timestamp.month, str(timestamp.month))

    if include_year:
        return f"{month_name} {timestamp.year}"

    return month_name

def filter_task_bug(df: pd.DataFrame):
    if df.empty or "IssueType" not in df.columns:
        return df.copy()

    return df[
        df["IssueType"]
        .apply(normalize_issue_type)
        .isin(TASK_BUG_TYPES)
    ].copy()

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

def render_kpis(df: pd.DataFrame):
    if df.empty:
        st.info("Nessun dato disponibile per i filtri selezionati.")
        return

    task_bug_df = filter_task_bug(df)

    task_bug_count = len(task_bug_df)
    task_bug_done = int(task_bug_df["Done"].sum()) if not task_bug_df.empty else 0
    task_bug_open = task_bug_count - task_bug_done

    unassigned_task_bug = 0
    cancelled_task_bug = 0
    blocked_task_bug = 0

    if not task_bug_df.empty:
        unassigned_task_bug = int(
            (task_bug_df["Assignee"].fillna("").str.strip() == "").sum()
        )

        cancelled_task_bug = int(
            task_bug_df["Stato"]
            .apply(normalize_status)
            .eq("ANNULLATO")
            .sum()
        )

        blocked_task_bug = int(
            task_bug_df["Stato"]
            .apply(normalize_status)
            .eq("BLOCCATO")
            .sum()
        )

    c1, c2, c3 = st.columns(3)

    with c1:
        render_metric_card(
            label="Task/Bug",
            value=task_bug_count,
        )

    with c2:
        render_metric_card(
            label="Task/Bug aperti",
            value=task_bug_open,
        )

    with c3:
        render_metric_card(
            label="Task/Bug completati",
            value=task_bug_done,
            color="#027A48",
            background="#ECFDF3",
        )

    c4, c5, c6 = st.columns(3)

    with c4:
        render_metric_card(
            label="Task/Bug non assegnati",
            value=unassigned_task_bug,
        )

    with c5:
        render_metric_card(
            label="Task/Bug annullati",
            value=cancelled_task_bug,
        )

    with c6:
        render_metric_card(
            label="Task/Bug bloccati",
            value=blocked_task_bug,
            color="#B54708",
            background="#FFFAEB",
        )

def render_status_panel(df: pd.DataFrame, key_suffix: str = "default"):
    st.subheader("Task/Bug per stato")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    status_df = (
        task_bug_df
        .groupby(["Stato", "StatusCategory"], dropna=False)
        .size()
        .reset_index(name="Task/Bug")
    )

    status_df["__order"] = status_df["Stato"].apply(get_status_sort_order)

    status_df = (
        status_df
        .sort_values(
            by=["__order", "Stato"],
            ascending=[True, True],
            kind="mergesort",
        )
        .drop(columns=["__order"])
        .reset_index(drop=True)
    )

    chart_df = status_df.copy()
    chart_df["Categoria"] = chart_df["Stato"].apply(get_status_color_group)

    ordered_statuses = status_df["Stato"].astype(str).tolist()

    fig = px.bar(
        chart_df,
        x="Stato",
        y="Task/Bug",
        color="Categoria",
        text="Task/Bug",
        title="Distribuzione Task/Bug per stato",
        color_discrete_map=STATUS_COLOR_MAP,
    )

    fig.update_layout(
        xaxis_title="Stato",
        yaxis_title="Numero Task/Bug",
        legend_title="",
    )

    fig.update_xaxes(
        categoryorder="array",
        categoryarray=ordered_statuses,
    )

    fig.update_traces(
        textposition="outside",
        marker_line_width=0,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"status_panel_chart_{key_suffix}",
    )

    st.dataframe(
        status_df,
        use_container_width=True,
        hide_index=True,
        key=f"status_panel_table_{key_suffix}",
    )

def render_status_category_panel(df: pd.DataFrame, key_suffix: str = "default"):
    st.subheader("Distribuzione Task/Bug per categoria")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    category_df = task_bug_df.copy()
    category_df["Categoria"] = category_df["Stato"].apply(get_status_color_group)

    grouped = (
        category_df
        .groupby("Categoria", dropna=False)
        .size()
        .reset_index(name="Task/Bug")
    )

    grouped["__order"] = grouped["Categoria"].map(
        {
            "Da fare": 0,
            "In corso": 1,
            "Completato": 2,
            "Altro": 3,
        }
    ).fillna(999)

    grouped = (
        grouped
        .sort_values(["__order", "Categoria"], ascending=[True, True])
        .drop(columns=["__order"])
        .reset_index(drop=True)
    )

    fig = px.pie(
        grouped,
        names="Categoria",
        values="Task/Bug",
        color="Categoria",
        hole=0.45,
        title="Distribuzione Task/Bug per categoria",
        color_discrete_map=STATUS_COLOR_MAP,
    )

    fig.update_traces(
        textinfo="percent",
        marker=dict(
            line=dict(
                color="#ffffff",
                width=2,
            )
        ),
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"status_category_chart_{key_suffix}",
    )

    st.dataframe(
        grouped,
        use_container_width=True,
        hide_index=True,
        key=f"status_category_table_{key_suffix}",
    )

def render_assignee_panel(df: pd.DataFrame, key_suffix: str = "default"):
    st.subheader("Task/Bug per assegnatario")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    assignee_df = task_bug_df.copy()

    assignee_df["Assignee"] = (
        assignee_df["Assignee"]
        .fillna("")
        .replace("", "Non assegnato")
    )

    grouped = (
        assignee_df
        .groupby("Assignee", dropna=False)
        .agg(
            TaskBug=("Issue", "count"),
            Completati=("Done", "sum"),
        )
        .reset_index()
    )

    grouped["Aperti"] = grouped["TaskBug"] - grouped["Completati"]

    grouped["Avanzamento %"] = (
        grouped["Completati"] / grouped["TaskBug"] * 100
    ).round(1)

    grouped = grouped.sort_values("TaskBug", ascending=False)

    fig = px.bar(
        grouped.head(25),
        x="Assignee",
        y=["Aperti", "Completati"],
        title="Task/Bug per assegnatario",
        barmode="stack",
        color_discrete_map=PEOPLE_STATUS_COLOR_MAP,
    )

    fig.update_layout(
        xaxis_title="Assegnatario",
        yaxis_title="Numero Task/Bug",
        legend_title="",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"assignee_panel_chart_{key_suffix}",
    )

    st.dataframe(
        grouped,
        use_container_width=True,
        hide_index=True,
        key=f"assignee_panel_table_{key_suffix}",
    )

def render_priority_panel(df: pd.DataFrame, key_suffix: str = "default"):
    st.subheader("Task/Bug per priorità cliente")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    priority_df = task_bug_df.copy()

    priority_df["Priorità cliente"] = (
        priority_df["Priority"]
        .fillna("")
        .replace("", NO_PRIORITY_LABEL)
    )

    grouped = (
        priority_df
        .groupby("Priorità cliente", dropna=False)
        .size()
        .reset_index(name="Task/Bug")
    )

    grouped["__order"] = grouped["Priorità cliente"].apply(get_priority_sort_order)
    grouped["__color_key"] = grouped["Priorità cliente"].apply(get_priority_color_key)

    grouped = (
        grouped
        .sort_values(
            by=["__order", "Task/Bug", "Priorità cliente"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )

    ordered_priorities = grouped["Priorità cliente"].astype(str).tolist()

    fig = px.bar(
        grouped,
        x="Priorità cliente",
        y="Task/Bug",
        color="__color_key",
        text="Task/Bug",
        title="Distribuzione Task/Bug per priorità cliente",
        color_discrete_map=PRIORITY_COLOR_MAP,
    )

    fig.update_layout(
        xaxis_title="Priorità cliente",
        yaxis_title="Numero Task/Bug",
        legend_title="Priorità",
        showlegend=False,
    )

    fig.update_xaxes(
        categoryorder="array",
        categoryarray=ordered_priorities,
    )

    fig.update_traces(
        textposition="outside",
        marker_line_width=0,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"priority_panel_chart_{key_suffix}",
    )

    table_df = grouped.drop(columns=["__order", "__color_key"])

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        key=f"priority_panel_table_{key_suffix}",
    )

def render_priority_monthly_panel(df: pd.DataFrame, key_suffix: str = "default"):
    st.subheader("Andamento mensile priorità cliente")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    if "Created" not in task_bug_df.columns:
        st.info("Data di creazione non disponibile per calcolare l'andamento mensile.")
        return

    monthly_df = task_bug_df.copy()

    monthly_df["Created"] = pd.to_datetime(
        monthly_df["Created"],
        errors="coerce",
    )

    monthly_df = monthly_df.dropna(subset=["Created"])

    if monthly_df.empty:
        st.info("Nessun Task/Bug con data di creazione disponibile.")
        return

    monthly_df["Priorità cliente"] = (
        monthly_df["Priority"]
        .fillna("")
        .replace("", NO_PRIORITY_LABEL)
    )

    monthly_df["MeseKey"] = (
        monthly_df["Created"]
        .dt.to_period("M")
        .astype(str)
    )

    years = monthly_df["Created"].dt.year.dropna().unique()
    include_year = len(years) > 1

    monthly_df["Mese"] = monthly_df["Created"].apply(
        lambda value: get_month_label(value, include_year=include_year)
    )

    monthly_df["Indice complessità"] = monthly_df["Priorità cliente"].apply(
        get_priority_complexity_score
    )

    grouped = (
        monthly_df
        .groupby(["MeseKey", "Mese", "Priorità cliente"], dropna=False)
        .size()
        .reset_index(name="Task/Bug")
    )

    grouped["__priority_order"] = grouped["Priorità cliente"].apply(
        get_priority_sort_order
    )

    grouped["__color_key"] = grouped["Priorità cliente"].apply(
        get_priority_color_key
    )

    grouped = (
        grouped
        .sort_values(
            by=["MeseKey", "__priority_order", "Priorità cliente"],
            ascending=[True, True, True],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )

    monthly_score_df = (
        monthly_df
        .groupby(["MeseKey", "Mese"], dropna=False)
        .agg(
            **{
                "Ticket": ("Issue", "count"),
                "Indice complessità medio": ("Indice complessità", "mean"),
                "Ticket Altissima": (
                    "Priorità cliente",
                    lambda values: sum(
                        normalize_priority(value).lower() == "altissima"
                        for value in values
                    ),
                ),
                "Ticket Alta": (
                    "Priorità cliente",
                    lambda values: sum(
                        normalize_priority(value).lower() == "alta"
                        for value in values
                    ),
                ),
            }
        )
        .reset_index()
        .sort_values("MeseKey")
    )

    monthly_score_df["Indice complessità medio"] = (
        monthly_score_df["Indice complessità medio"]
        .round(2)
    )

    monthly_score_df["% Altissima"] = (
        monthly_score_df["Ticket Altissima"] / monthly_score_df["Ticket"] * 100
    ).round(1)

    first_month_score = 0
    last_month_score = 0
    score_delta = 0

    if not monthly_score_df.empty:
        first_month_score = monthly_score_df.iloc[0]["Indice complessità medio"]
        last_month_score = monthly_score_df.iloc[-1]["Indice complessità medio"]
        score_delta = round(last_month_score - first_month_score, 2)

    c1, c2, c3 = st.columns(3)

    with c1:
        render_metric_card(
            label="Indice complessità ultimo mese",
            value=last_month_score,
            color="#2563EB",
            background="#EFF6FF",
        )

    with c2:
        render_metric_card(
            label="Variazione indice",
            value=score_delta,
            color="#B54708" if score_delta > 0 else "#027A48",
            background="#FFFAEB" if score_delta > 0 else "#ECFDF3",
        )

    with c3:
        latest_altissima_percentage = 0

        if not monthly_score_df.empty:
            latest_altissima_percentage = monthly_score_df.iloc[-1]["% Altissima"]

        render_metric_card(
            label="% Altissima ultimo mese",
            value=f"{latest_altissima_percentage}%",
            color="#DC2626",
            background="#FEF2F2",
        )

    st.caption(
        "Il grafico mostra la distribuzione mensile delle priorità cliente "
        "sui Task/Bug creati nel periodo filtrato. "
        "L'indice complessità è calcolato come score indicativo: "
        "Altissima=5, Alta=4, Media=3, Bassa=2, Fase 2=1."
    )

    month_order_df = (
        monthly_df[["MeseKey", "Mese"]]
        .drop_duplicates()
        .sort_values("MeseKey")
    )

    ordered_months = month_order_df["Mese"].tolist()

    ordered_priorities = [
        priority
        for priority in PRIORITY_ORDER
        if priority in grouped["Priorità cliente"].unique().tolist()
    ]

    remaining_priorities = sorted(
        [
            priority
            for priority in grouped["Priorità cliente"].unique().tolist()
            if priority not in ordered_priorities
        ]
    )

    ordered_priorities = ordered_priorities + remaining_priorities

    fig = px.bar(
        grouped,
        x="Mese",
        y="Task/Bug",
        color="Priorità cliente",
        text="Task/Bug",
        title="Distribuzione mensile Task/Bug per priorità cliente",
        color_discrete_map=PRIORITY_COLOR_MAP,
        category_orders={
            "Mese": ordered_months,
            "Priorità cliente": ordered_priorities,
        },
    )

    fig.update_layout(
        xaxis_title="Mese creazione ticket",
        yaxis_title="Numero Task/Bug",
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
        key=f"priority_monthly_chart_{key_suffix}",
    )

    monthly_score_display_df = monthly_score_df.drop(columns=["MeseKey"])

    st.dataframe(
        monthly_score_display_df,
        use_container_width=True,
        hide_index=True,
        key=f"priority_monthly_score_table_{key_suffix}",
        column_config={
            "Indice complessità medio": st.column_config.NumberColumn(
                "Indice complessità medio",
                format="%.2f",
            ),
            "% Altissima": st.column_config.NumberColumn(
                "% Altissima",
                format="%.1f%%",
            ),
        },
    )

    table_df = grouped.drop(columns=["MeseKey", "__priority_order", "__color_key"])

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        key=f"priority_monthly_detail_table_{key_suffix}",
    )
