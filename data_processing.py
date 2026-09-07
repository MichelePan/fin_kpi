import io
import pandas as pd

from datetime import datetime, date

DONE_STATUS_KEYWORDS = [
    "done",
    "closed",
    "chiuso",
    "chiusa",
    "completato",
    "completata",
    "resolved",
    "risolto",
    "risolta",
    "rilasciato",
    "rilasciata",
]

def parse_jira_datetime(value):
    if not value:
        return None

    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None

def parse_jira_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except Exception:
        return None

def is_done_status(status_name: str):
    status = (status_name or "").strip().lower()
    return any(keyword in status for keyword in DONE_STATUS_KEYWORDS)

def extract_epic_key(fields: dict, epic_link_field_id: str | None):
    if epic_link_field_id:
        epic_value = fields.get(epic_link_field_id)

        if isinstance(epic_value, str) and epic_value.strip():
            return epic_value.strip()

    parent = fields.get("parent") or {}

    if parent:
        parent_fields = parent.get("fields") or {}
        parent_issue_type = (parent_fields.get("issuetype") or {}).get("name", "")

        if parent_issue_type.lower() == "epic":
            return parent.get("key", "")

    return ""

def extract_epic_name(fields: dict):
    parent = fields.get("parent") or {}

    if not parent:
        return ""

    parent_fields = parent.get("fields") or {}
    parent_issue_type = (parent_fields.get("issuetype") or {}).get("name", "")

    if parent_issue_type.lower() == "epic":
        return parent_fields.get("summary", "") or ""

    return ""

def extract_sprint_name(fields: dict, sprint_field_id: str | None):
    if not sprint_field_id:
        return ""

    sprint_value = fields.get(sprint_field_id)

    if not sprint_value:
        return ""

    if isinstance(sprint_value, list) and len(sprint_value) > 0:
        latest_sprint = sprint_value[-1]

        if isinstance(latest_sprint, dict):
            return latest_sprint.get("name", "") or ""

        return str(latest_sprint)

    if isinstance(sprint_value, dict):
        return sprint_value.get("name", "") or ""

    return str(sprint_value)

def build_issues_dataframe(
    issues: list[dict],
    epic_link_field_id: str | None = None,
    sprint_field_id: str | None = None,
):
    rows = []
    today = date.today()

    for issue in issues:
        fields = issue.get("fields") or {}

        issue_key = issue.get("key", "")
        summary = fields.get("summary", "") or ""

        issue_type = (fields.get("issuetype") or {}).get("name", "") or ""
        status = (fields.get("status") or {}).get("name", "") or ""

        status_category = (
            ((fields.get("status") or {}).get("statusCategory") or {}).get("name", "")
            or ""
        )

        assignee = (fields.get("assignee") or {}).get("displayName", "") or ""
        reporter = (fields.get("reporter") or {}).get("displayName", "") or ""
        priority = (fields.get("priority") or {}).get("name", "") or ""

        created_dt = parse_jira_datetime(fields.get("created"))
        updated_dt = parse_jira_datetime(fields.get("updated"))
        due_date = parse_jira_date(fields.get("duedate"))
        resolution_dt = parse_jira_datetime(fields.get("resolutiondate"))

        created_date = created_dt.date() if created_dt else None
        updated_date = updated_dt.date() if updated_dt else None
        resolution_date = resolution_dt.date() if resolution_dt else None

        days_open = None

        if created_date:
            end_date = resolution_date or today
            days_open = (end_date - created_date).days

        days_since_update = None

        if updated_date:
            days_since_update = (today - updated_date).days

        epic_key = extract_epic_key(fields, epic_link_field_id)
        epic_name = extract_epic_name(fields)
        sprint_name = extract_sprint_name(fields, sprint_field_id)

        done = is_done_status(status) or status_category.lower() == "done"

        rows.append(
            {
                "Issue": issue_key,
                "Summary": summary,
                "IssueType": issue_type,
                "Stato": status,
                "StatusCategory": status_category,
                "Done": done,
                "Assignee": assignee,
                "Reporter": reporter,
                "Priority": priority,
                "EpicKey": epic_key,
                "EpicName": epic_name,
                "Sprint": sprint_name,
                "Created": created_date,
                "Updated": updated_date,
                "DueDate": due_date,
                "ResolutionDate": resolution_date,
                "DaysOpen": days_open,
                "DaysSinceUpdate": days_since_update,
                "Url": "",
            }
        )

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    for column in ["Created", "Updated", "DueDate", "ResolutionDate"]:
        df[column] = pd.to_datetime(df[column], errors="coerce")

    df["DaysOpen"] = pd.to_numeric(df["DaysOpen"], errors="coerce")
    df["DaysSinceUpdate"] = pd.to_numeric(df["DaysSinceUpdate"], errors="coerce")

    return df

def add_issue_urls(df: pd.DataFrame, jira_domain: str):
    if df.empty:
        return df

    df = df.copy()

    df["Url"] = df["Issue"].apply(
        lambda key: f"https://{jira_domain}/browse/{key}" if key else ""
    )

    return df

def apply_filters(
    df: pd.DataFrame,
    statuses: list[str] | None = None,
    issue_types: list[str] | None = None,
    assignees: list[str] | None = None,
    priorities: list[str] | None = None,
    epics: list[str] | None = None,
    sprints: list[str] | None = None,
    only_open: bool = False,
):
    if df.empty:
        return df

    filtered = df.copy()

    if statuses:
        filtered = filtered[filtered["Stato"].isin(statuses)]

    if issue_types:
        filtered = filtered[filtered["IssueType"].isin(issue_types)]

    if assignees:
        filtered = filtered[filtered["Assignee"].isin(assignees)]

    if priorities:
        filtered = filtered[filtered["Priority"].isin(priorities)]

    if epics:
        filtered = filtered[
            filtered["EpicName"].isin(epics) | filtered["EpicKey"].isin(epics)
        ]

    if sprints and "Sprint" in filtered.columns:
        filtered = filtered[filtered["Sprint"].isin(sprints)]

    if only_open:
        filtered = filtered[filtered["Done"] == False]

    return filtered

def create_excel_export(df: pd.DataFrame):
    output = io.BytesIO()

    export_df = df.copy()

    columns = [
        "Issue",
        "Summary",
        "IssueType",
        "Stato",
        "StatusCategory",
        "Assignee",
        "Reporter",
        "Priority",
        "EpicKey",
        "EpicName",
        "Created",
        "Updated",
        "DueDate",
        "ResolutionDate",
        "DaysOpen",
        "DaysSinceUpdate",
        "StimaOre",
        "Stima (in ore)",
        "Url",
    ]

    existing_columns = [
        column
        for column in columns
        if column in export_df.columns
    ]

    export_df = export_df[existing_columns]

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Issues")

        workbook = writer.book
        worksheet = writer.sheets["Issues"]

        date_format = workbook.add_format({"num_format": "dd/mm/yyyy"})
        integer_format = workbook.add_format({"num_format": "0"})
        number_format = workbook.add_format({"num_format": "0.00"})

        worksheet.set_column("A:A", 14)
        worksheet.set_column("B:B", 60)
        worksheet.set_column("C:E", 18)
        worksheet.set_column("F:G", 25)
        worksheet.set_column("H:H", 16)
        worksheet.set_column("I:J", 30)
        worksheet.set_column("K:N", 14, date_format)
        worksheet.set_column("O:P", 16, integer_format)
        worksheet.set_column("Q:R", 16, number_format)
        worksheet.set_column("S:S", 60)

    output.seek(0)

    return output
