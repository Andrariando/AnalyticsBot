from typing import Any, Dict, List, Optional
from app.schemas.file import FileProfileSummary


def format_welcome_message() -> str:
    """Format the /start onboarding guide."""
    return (
        "📊 *Autonomous Business Analytics Operating System*\n\n"
        "I am an enterprise AI analytics platform combining consultant-level business framing with deterministic Python computation.\n\n"
        "🔹 *Core Commands:*\n"
        "• `/start` - Display this welcome guide\n"
        "• `/projects` - List your active projects\n"
        "• `/status` - Check current project phase and state\n"
        "• `/learn` + file - Ingest methodology or domain paper into Knowledge Base\n"
        "• `/new <title>` - Start a fresh analytical project\n\n"
        "📁 *Getting Started:*\n"
        "Simply send a business question along with your CSV, Excel, PDF, or text datasets. "
        "I will profile the data, propose a methodology, compute models, enforce critic review gates, and generate executive action queues."
    )


def format_file_ingested_message(filename: str, rows: int, cols: int, file_id: str) -> str:
    """Format receipt when a file is ingested."""
    return (
        f"✅ *File Ingested Successfully*\n\n"
        f"• *File:* `{filename}`\n"
        f"• *Dimensions:* `{rows:,}` rows × `{cols}` columns\n"
        f"• *Status:* Stored in isolated project workspace\n"
        f"• *ID:* `{file_id[:8]}...`\n\n"
        f"👉 *Awaiting Your Action:*\n"
        f"The dataset is ready. Choose an action button below or type what you would like to analyze."
    )


def format_profile_summary_telegram(summary: FileProfileSummary) -> str:
    """Format data profiling summary for mobile display."""
    alerts_text = ""
    if summary.quality_alerts:
        alerts_text = "\n⚠️ *Data Quality Alerts:*\n" + "\n".join(f"• {a}" for a in summary.quality_alerts[:5])

    keys_text = ", ".join(summary.potential_grain) if summary.potential_grain else "None detected"

    date_text = "N/A"
    if summary.date_coverage:
        earliest = summary.date_coverage.get("earliest_date", "")[:10]
        latest = summary.date_coverage.get("latest_date", "")[:10]
        date_text = f"{earliest} to {latest}"

    return (
        f"🔍 *Data Profile: {summary.filename}*\n\n"
        f"• *Rows:* `{summary.row_count:,}`\n"
        f"• *Columns:* `{summary.column_count}`\n"
        f"• *Duplicate Rows:* `{summary.duplicate_rows_count:,}`\n"
        f"• *Potential Key/Grain:* `{keys_text}`\n"
        f"• *Time Horizon:* `{date_text}`"
        f"{alerts_text}\n\n"
        f"👉 *Next Step:* Click an action below or describe your analytical objective."
    )


def format_project_summary(
    state_or_title: Any,
    phase: Optional[str] = None,
    status: Optional[str] = None,
    file_count: Optional[int] = None,
    ass_count: Optional[int] = None,
    dec_count: Optional[int] = None,
) -> str:
    """Format project status summary for Telegram, accepting either state dict or individual fields."""
    if isinstance(state_or_title, dict):
        title = state_or_title.get("title", "Untitled Project")
        phase = state_or_title.get("current_phase", "INITIALIZED")
        status = state_or_title.get("status", "ACTIVE")
        files = state_or_title.get("files", [])
        file_count = len(files) if isinstance(files, list) else 0
        assumptions = state_or_title.get("assumptions", [])
        ass_count = len(assumptions) if isinstance(assumptions, list) else 0
        decisions = state_or_title.get("decisions", [])
        dec_count = len(decisions) if isinstance(decisions, list) else 0
    else:
        title = str(state_or_title)
        phase = phase or "INITIALIZED"
        status = status or "ACTIVE"
        file_count = file_count or 0
        ass_count = ass_count or 0
        dec_count = dec_count or 0

    return (
        f"📊 *Project Status: {title}*\n\n"
        f"• *Current Phase:* `{phase}`\n"
        f"• *Status:* `{status}`\n"
        f"• *Files Ingested:* `{file_count}`\n"
        f"• *Assumptions Logged:* `{ass_count}`\n"
        f"• *Decisions Recorded:* `{dec_count}`\n\n"
        f"👉 *Next Action:* Select an action below or type instructions to continue."
    )
