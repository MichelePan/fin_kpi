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
    "ANALISI": "In lavorazione",
    "IN CORSO": "In lavorazione",
    "ON HOLD TEMP": "In lavorazione",
    "IN REVISIONE/TEST": "In lavorazione",
    "BLOCCATO": "In lavorazione",
    "ANNULLATO": "Chiusura",
    "TICKET FIL NON CHIUSO": "Chiusura",
    "VERBALE CHIUSO": "Chiusura",
}

STATUS_COLOR_MAP = {
    "Da fare": "#7DD3FC",
    "In lavorazione": "#2563EB",
    "Chiusura": "#16A34A",
    "Altro": "#94A3B8",
}

def normalize_issue_type(value):
    if value is None:
        return ""

    return str(value).strip().lower()

def normalize_status(value):
    if value is None:
        return ""

    return str(value).strip().upper()

def get_status_sort_order(status):
    normalized_status = normalize_status(status)

    return STATUS_ORDER_MAP.get(normalized_status, 999)

def get_status_color_group(status):
    normalized_status = normalize_status(status)

    return STATUS_COLOR_GROUPS.get(normalized_status, "Altro")

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
    chart_df["Raggruppamento"] = chart_df["Stato"].apply(get_status_color_group)

    ordered_statuses = status_df["Stato"].astype(str).tolist()

    fig = px.bar(
        chart_df,
        x="Stato",
        y="Task/Bug",
        color="Raggruppamento",
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
    st.subheader("Categorie stato Jira")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    category_df = (
        task_bug_df
        .groupby("StatusCategory", dropna=False)
        .size()
        .reset_index(name="Task/Bug")
        .sort_values("Task/Bug", ascending=False)
    )

    fig = px.pie(
        category_df,
        names="StatusCategory",
        values="Task/Bug",
        hole=0.45,
        title="Distribuzione Task/Bug per categoria Jira",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"status_category_chart_{key_suffix}",
    )

    st.dataframe(
        category_df,
        use_container_width=True,
        hide_index=True,
        key=f"status_category_table_{key_suffix}",
    )

def render_epic_panel(df: pd.DataFrame, key_suffix: str = "default"):
    st.subheader("Avanzamento per Epic")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    epic_df = task_bug_df.copy()

    epic_df["Epic"] = epic_df["EpicName"]

    epic_df.loc[
        epic_df["Epic"].fillna("").str.strip() == "",
        "Epic",
    ] = epic_df["EpicKey"]

    epic_df.loc[
        epic_df["Epic"].fillna("").str.strip() == "",
        "Epic",
    ] = "Senza Epic"

    grouped = (
        epic_df
        .groupby("Epic", dropna=False)
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
        grouped.head(20),
        x="Epic",
        y=["Aperti", "Completati"],
        title="Task/Bug aperti e completati per Epic",
        barmode="stack",
        color_discrete_map={
            "Aperti": "#2563EB",
            "Completati": "#16A34A",
        },
    )

    fig.update_layout(
        xaxis_title="Epic",
        yaxis_title="Numero Task/Bug",
        legend_title="",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"epic_panel_chart_{key_suffix}",
    )

    st.dataframe(
        grouped,
        use_container_width=True,
        hide_index=True,
        key=f"epic_panel_table_{key_suffix}",
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
        color_discrete_map={
            "Aperti": "#2563EB",
            "Completati": "#16A34A",
        },
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
    st.subheader("Task/Bug per priorità")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    priority_df = task_bug_df.copy()

    priority_df["Priority"] = (
        priority_df["Priority"]
        .fillna("")
        .replace("", "Nessuna priorità")
    )

    grouped = (
        priority_df
        .groupby("Priority", dropna=False)
        .size()
        .reset_index(name="Task/Bug")
        .sort_values("Task/Bug", ascending=False)
    )

    fig = px.bar(
        grouped,
        x="Priority",
        y="Task/Bug",
        text="Task/Bug",
        title="Distribuzione Task/Bug per priorità",
        color_discrete_sequence=["#2563EB"],
    )

    fig.update_layout(
        xaxis_title="Priorità",
        yaxis_title="Numero Task/Bug",
    )

    fig.update_traces(textposition="outside")

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"priority_panel_chart_{key_suffix}",
    )

    st.dataframe(
        grouped,
        use_container_width=True,
        hide_index=True,
        key=f"priority_panel_table_{key_suffix}",
    )

def render_age_panel(df: pd.DataFrame, key_suffix: str = "default"):
    st.subheader("Task/Bug aperti da più tempo")

    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    task_bug_df = filter_task_bug(df)

    if task_bug_df.empty:
        st.info("Nessun Task o Bug disponibile per i filtri selezionati.")
        return

    open_df = task_bug_df[task_bug_df["Done"] == False].copy()

    if open_df.empty:
        st.success("Non ci sono Task/Bug aperti nel perimetro selezionato.")
        return

    open_df = open_df.sort_values("DaysOpen", ascending=False)

    columns = [
        "Issue",
        "Summary",
        "IssueType",
        "Stato",
        "Assignee",
        "Priority",
        "EpicName",
        "Created",
        "Updated",
        "DaysOpen",
        "DaysSinceUpdate",
        "Url",
    ]

    existing_columns = [
        column
        for column in columns
        if column in open_df.columns
    ]

    st.dataframe(
        open_df[existing_columns].head(30),
        use_container_width=True,
        hide_index=True,
        key=f"age_panel_table_{key_suffix}",
        column_config={
            "Url": st.column_config.LinkColumn("Jira"),
        },
    )
