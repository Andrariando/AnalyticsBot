import asyncio
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlalchemy import select
from app.config import settings
from app.db.session import async_session_factory, init_db
from app.db.models import User, Project, ProjectFile, KBDocument, Artifact
from app.tools.file_tools import FileIngestionService
from app.tools.profiling_tools import DatasetProfiler
from app.agents.supervisor import SupervisorAgent
from app.core.memory import ProjectMemoryManager
from app.bot.formatters import format_welcome_message, format_project_summary

logger = logging.getLogger(__name__)


async def safe_edit_message_text(
    msg,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "Markdown",
) -> None:
    """Edit message text with automatic fallback for markdown parse errors and message length limits."""
    if not msg:
        return
    max_len = 4000
    display_text = text if len(text) <= max_len else text[:max_len] + "\n\n...(truncated for display)"
    try:
        await msg.edit_text(display_text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Failed to edit message with parse_mode={parse_mode}: {e}. Retrying without markdown.")
        try:
            await msg.edit_text(display_text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Failed to edit message even without markdown: {e2}")


async def safe_reply_text(
    target,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "Markdown",
):
    """Reply text with automatic fallback for markdown parse errors and message length limits."""
    if not target:
        return None
    msg = target.message if hasattr(target, "message") and target.message else target
    max_len = 4000
    display_text = text if len(text) <= max_len else text[:max_len] + "\n\n...(truncated for display)"
    try:
        return await msg.reply_text(display_text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Failed to reply with parse_mode={parse_mode}: {e}. Retrying without markdown.")
        try:
            return await msg.reply_text(display_text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Failed to reply even without markdown: {e2}")
            return None


def get_default_action_keyboard() -> InlineKeyboardMarkup:
    """Construct interactive Telegram inline keyboard buttons for common executive actions."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve & Run OR-Tools", callback_data="btn_approve_or"),
            InlineKeyboardButton("📓 Build Python Notebook", callback_data="btn_build_notebook"),
        ],
        [
            InlineKeyboardButton("🌐 Multi-Echelon MEIO", callback_data="btn_meio"),
            InlineKeyboardButton("📊 Render Decision Charts", callback_data="btn_export_charts"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_or_create_user(telegram_user) -> User:
    """Retrieve or create user by telegram ID in database."""
    async with async_session_factory() as db:
        stmt = select(User).where(User.telegram_id == telegram_user.id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=telegram_user.id,
                username=telegram_user.username or f"user_{telegram_user.id}",
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user


async def get_active_project_for_user(user_id: str) -> Project:
    """Get the most recent active project for a user or create default."""
    async with async_session_factory() as db:
        stmt = select(Project).where(Project.user_id == user_id).order_by(Project.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        project = res.scalar_one_or_none()
        if not project:
            project = Project(
                user_id=user_id,
                title="Default Analytics Project",
                current_phase="INITIALIZED",
                status="ACTIVE",
            )
            db.add(project)
            await db.commit()
            await db.refresh(project)
            FileIngestionService.initialize_project_workspace(project.id)
        return project


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start."""
    if not update.effective_user or not update.message:
        return
    await get_or_create_user(update.effective_user)
    await safe_reply_text(
        update,
        format_welcome_message(),
        reply_markup=get_default_action_keyboard(),
    )


async def new_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /new <title>."""
    if not update.effective_user or not update.message:
        return
    user = await get_or_create_user(update.effective_user)
    title = " ".join(context.args) if context.args else "New Analytics Project"

    async with async_session_factory() as db:
        project = Project(
            user_id=user.id,
            title=title,
            current_phase="INITIALIZED",
            status="ACTIVE",
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        FileIngestionService.initialize_project_workspace(project.id)

    await safe_reply_text(
        update,
        (
            f"🎯 *New Project Initialized:*\n\n"
            f"• *Title:* `{title}`\n"
            f"• *ID:* `{project.id}`\n"
            f"• *Phase:* `INITIALIZED`\n\n"
            f"👉 *Next Action:* Upload your CSV/Excel datasets or click an action below."
        ),
        reply_markup=get_default_action_keyboard(),
    )


async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /projects."""
    if not update.effective_user or not update.message:
        return
    user = await get_or_create_user(update.effective_user)
    async with async_session_factory() as db:
        stmt = select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc()).limit(5)
        res = await db.execute(stmt)
        projects = res.scalars().all()

    if not projects:
        await safe_reply_text(update, "You have no active projects. Use `/new <title>` to start one.")
        return

    text = "📁 *Your Recent Analytics Projects:*\n\n"
    for p in projects:
        text += f"• *{p.title}* (`{p.current_phase}` | `{p.status}`)\n  ID: `{p.id[:8]}...`\n"
    text += "\n👉 *Next Step:* Upload files to your project or select an action."
    await safe_reply_text(update, text)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status."""
    if not update.effective_user or not update.message:
        return
    user = await get_or_create_user(update.effective_user)
    project = await get_active_project_for_user(user.id)

    async with async_session_factory() as db:
        state_data = await ProjectMemoryManager.get_project_state(db, project.id)

    summary_text = format_project_summary(state_data)
    await safe_reply_text(
        update,
        summary_text,
        reply_markup=get_default_action_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    if not update.message:
        return
    help_text = (
        "📖 *Autonomous Analytics Operating System Commands:*\n\n"
        "• `/start` - Overview and quick actions\n"
        "• `/new <Title>` - Create a new isolated workspace\n"
        "• `/projects` - List your recent projects\n"
        "• `/status` - View current state, files, and decisions\n"
        "• `/learn` + file - Ingest PDF/whitepaper into Knowledge Base\n"
        "• `/help` - Show this guide\n\n"
        "💡 *Interactive Actions:* Attach files to ingest, chat directly, or click the inline buttons below."
    )
    await safe_reply_text(
        update,
        help_text,
        reply_markup=get_default_action_keyboard(),
    )


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file uploads in Telegram with proactive status & guidance."""
    if not update.effective_user or not update.message or not update.message.document:
        return

    user = await get_or_create_user(update.effective_user)
    project = await get_active_project_for_user(user.id)
    doc = update.message.document

    caption = (update.message.caption or "").strip()
    if caption.startswith("/learn"):
        await _handle_knowledge_ingestion(update, context, doc, project)
        return

    status_msg = await safe_reply_text(update, f"📥 *Ingesting* `{doc.file_name}`...")

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        file_bytes = BytesIO()
        await tg_file.download_to_memory(file_bytes)
        file_bytes.seek(0)
        content_bytes = file_bytes.read()

        async with async_session_factory() as db:
            project_file = await FileIngestionService.save_and_ingest_file(
                db=db,
                project_id=project.id,
                filename=doc.file_name or "uploaded_file",
                content_bytes=content_bytes,
            )

        profiling_msg = ""
        if project_file.file_type in ["CSV", "EXCEL"]:
            profile_res = DatasetProfiler.profile_tabular_file(
                file_path=Path(project_file.raw_path),
                file_id=project_file.id,
            )
            profiling_msg = (
                f"\n\n📊 *Automated Profile:*\n"
                f"• Rows: `{profile_res.row_count:,}` | Columns: `{profile_res.column_count}`\n"
                f"• Primary Key: `{profile_res.primary_key_candidate or 'None'}`\n"
                f"• Null Rate: `{profile_res.quality_metrics.get('overall_null_rate_pct', 0.0)}%`"
            )

        receipt = (
            f"✅ *File Ingested Successfully:*\n"
            f"• `{project_file.filename}` ({project_file.file_type}){profiling_msg}\n\n"
            f"👉 *Awaiting Your Action:*\n"
            f"The dataset is stored in your workspace. What would you like to analyze?\n"
            f"• Click an action button below (e.g. *Approve & Run OR-Tools*, *Build Python Notebook*)\n"
            f"• Or type your instruction/question directly in chat."
        )

        await safe_edit_message_text(
            status_msg,
            receipt,
            reply_markup=get_default_action_keyboard(),
        )

    except Exception as e:
        logger.error(f"Failed to ingest document: {e}", exc_info=True)
        await safe_edit_message_text(status_msg, f"❌ Error ingesting file: `{str(e)}`")


async def _handle_knowledge_ingestion(update: Update, context: ContextTypes.DEFAULT_TYPE, doc, project: Project) -> None:
    """Handle /learn domain document ingestion."""
    status_msg = await safe_reply_text(update, f"🧠 *Ingesting into Knowledge Base:* `{doc.file_name}`...")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        file_bytes = BytesIO()
        await tg_file.download_to_memory(file_bytes)
        file_bytes.seek(0)
        content = file_bytes.read().decode("utf-8", errors="replace")

        async with async_session_factory() as db:
            kb_doc = KBDocument(
                source=doc.file_name or "uploaded_kb_doc",
                document_type="USER_UPLOAD",
                content=content,
            )
            db.add(kb_doc)
            await db.commit()

        await safe_edit_message_text(
            status_msg,
            (
                f"✅ *Knowledge Ingested:* `{doc.file_name}` has been added to project memory.\n\n"
                f"👉 *Next Action:* Select an analysis action or ask questions incorporating this methodology."
            ),
            reply_markup=get_default_action_keyboard(),
        )
    except Exception as e:
        await safe_edit_message_text(status_msg, f"❌ Failed to ingest knowledge document: `{e}`")


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle interactive inline keyboard clicks."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data
    user = await get_or_create_user(update.effective_user)
    project = await get_active_project_for_user(user.id)

    prompt_map = {
        "btn_approve_or": "The proposed approach is approved. Please execute the complete operations research suite (velocity segmentation, dynamic stocking policy, OR-Tools lateral rebalancing, and disposition).",
        "btn_build_notebook": "Please write custom Python code to analyze our dataset and compile it into an interactive Jupyter Notebook (.ipynb).",
        "btn_meio": "Please execute Multi-Echelon Inventory Optimization (MEIO) to optimize safety stock positioning between our central hub and regional spoke DCs.",
        "btn_export_charts": "Please generate high-resolution decision charts for Pareto velocity concentration and warehouse pallet utilization.",
    }

    user_text = prompt_map.get(data, data)
    await safe_reply_text(query.message, f"🔘 *Action Triggered:* _{user_text}_\n\nExecuting...")

    await _process_supervisor_message(
        update=update,
        context=context,
        user=user,
        project=project,
        user_text=user_text,
    )


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages by invoking the Supervisor Agent."""
    if not update.effective_user or not update.message or not update.message.text:
        return

    user = await get_or_create_user(update.effective_user)
    project = await get_active_project_for_user(user.id)
    text = update.message.text.strip()

    await _process_supervisor_message(
        update=update,
        context=context,
        user=user,
        project=project,
        user_text=text,
    )


async def _process_supervisor_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    project: Project,
    user_text: str,
) -> None:
    """Execute a turn with the Supervisor Agent, reply to Telegram, and send generated charts/files."""
    target_msg = update.message or (update.callback_query.message if update.callback_query else None)
    status_msg = await safe_reply_text(target_msg, "🤔 *Analyzing dataset and executing analytical tools...*")

    project_dir = FileIngestionService.get_project_dir(project.id)
    charts_dir = project_dir / "charts"
    outputs_dir = project_dir / "outputs"

    pre_charts = set(charts_dir.glob("*.png")) if charts_dir.exists() else set()
    pre_outputs = set(outputs_dir.glob("*.*")) if outputs_dir.exists() else set()

    try:
        supervisor = SupervisorAgent()
        async with async_session_factory() as db:
            agent_res = await supervisor.execute_turn(
                db=db,
                project_id=project.id,
                user_message=user_text,
                chat_id=update.effective_user.id,
            )

        tools_executed_msg = ""
        if agent_res.tool_calls:
            tools_summary = ", ".join([f"`{t.tool_name}`" for t in agent_res.tool_calls])
            tools_executed_msg = f"⚙️ *Tools Executed:* {tools_summary}\n\n"

        reply_text = f"{tools_executed_msg}{agent_res.content}"

        # Proactively prompt the user if the response doesn't already contain a clear call-to-action
        cta_keywords = ["what would you like", "next step", "approve", "choose", "proceed", "select", "waiting", "awaiting"]
        if not any(k in reply_text.lower() for k in cta_keywords):
            reply_text += (
                "\n\n👉 *Next Step / Awaiting Your Input:*\n"
                "Please review the results above. You can approve the recommendations, request drill-downs, click an action below, or type your next question."
            )

        await safe_edit_message_text(
            status_msg,
            reply_text,
            reply_markup=get_default_action_keyboard(),
        )

        # Check for newly generated charts and send as photos
        if charts_dir.exists():
            post_charts = set(charts_dir.glob("*.png"))
            new_charts = post_charts - pre_charts
            for chart_p in sorted(new_charts):
                with open(chart_p, "rb") as photo_f:
                    try:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo_f,
                            caption=f"📈 Generated Chart: {chart_p.name}",
                        )
                    except Exception as pe:
                        logger.warning(f"Failed to send chart photo: {pe}")

        # Check for newly generated outputs (.csv, .ipynb, .md) and send as documents
        if outputs_dir.exists():
            post_outputs = set(outputs_dir.glob("*.*"))
            new_outputs = post_outputs - pre_outputs
            for out_p in sorted(new_outputs):
                if out_p.suffix in [".csv", ".ipynb", ".md"]:
                    with open(out_p, "rb") as doc_f:
                        try:
                            await context.bot.send_document(
                                chat_id=update.effective_chat.id,
                                document=doc_f,
                                caption=f"📄 Generated Deliverable: {out_p.name}",
                            )
                        except Exception as de:
                            logger.warning(f"Failed to send deliverable document: {de}")

    except Exception as e:
        logger.error(f"Error in supervisor execution: {e}", exc_info=True)
        error_msg = (
            f"⚠️ *Supervisor Notice:* `{str(e)}`\n\n"
            f"👉 *Action Needed:* Please check that the required datasets (e.g. weekly demand, inventory, warehouses) are uploaded, or specify what analysis you would like to run."
        )
        await safe_edit_message_text(status_msg, error_msg, reply_markup=get_default_action_keyboard())


def get_bot_app() -> Optional[Application]:
    """Build telegram application with commands, message handlers, and inline button callbacks."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("new", new_project_command))
    app.add_handler(CommandHandler("projects", projects_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    return app


async def start_telegram_bot() -> None:
    """Entrypoint to run telegram bot in polling mode."""
    await init_db()
    app = get_bot_app()
    if not app:
        logger.warning("Telegram bot token not configured.")
        return
    logger.info("Starting Telegram Bot long-polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
