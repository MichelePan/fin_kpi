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

PRIORITY_ORDER = [
 "Altissima",
 "Fase 2",
 "Nessuna priorità cliente",
]

PRIORITY_COLOR_MAP = {
 "Altissima": "#DC2626",
 "Fase 2": "#7DD3FC",
 "Nessuna priorità cliente": "#94A3B8",
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
 textinfo="label+percent+value",
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
 .replace("", "Nessuna priorità cliente")
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
