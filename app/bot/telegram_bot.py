import asyncio
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlalchemy import select
from app.config import settings
from app.db.session import async_session_factory
from app.db.models import User, Project, ProjectFile, KBDocument, Artifact
from app.tools.file_tools import FileIngestionService
from app.tools.profiling_tools import DatasetProfiler
from app.agents.supervisor import SupervisorAgent
from app.core.memory import ProjectMemoryManager
from app.bot.formatters import format_welcome_message, format_project_summary

logger = logging.getLogger(__name__)


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
    await update.message.reply_text(format_welcome_message(), parse_mode="Markdown")


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

    await update.message.reply_text(
        f"🎯 *New Project Initialized:*\n\n• *Title:* `{title}`\n• *ID:* `{project.id}`\n• *Phase:* `INITIALIZED`\n\nUpload your data files or describe your analytical question.",
        parse_mode="Markdown",
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
        await update.message.reply_text("You have no active projects. Use `/new <title>` to start one.", parse_mode="Markdown")
        return

    text = "📁 *Your Recent Analytics Projects:*\n\n"
    for p in projects:
        text += f"• *{p.title}* (`{p.current_phase}` | `{p.status}`)\n  ID: `{p.id[:8]}...`\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status."""
    if not update.effective_user or not update.message:
        return
    user = await get_or_create_user(update.effective_user)
    project = await get_active_project_for_user(user.id)

    async with async_session_factory() as db:
        state = await ProjectMemoryManager.get_project_state(db, project.id)

    file_count = len(state.get("files", []))
    dec_count = len(state.get("decisions", []))
    ass_count = len(state.get("assumptions", []))

    text = (
        f"📊 *Project Status: {project.title}*\n\n"
        f"• *Phase:* `{project.current_phase}`\n"
        f"• *Status:* `{project.status}`\n"
        f"• *Files Ingested:* `{file_count}`\n"
        f"• *Assumptions Logged:* `{ass_count}`\n"
        f"• *Decisions Recorded:* `{dec_count}`\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    if not update.message:
        return
    help_text = (
        "💡 *Available Bot Commands:*\n\n"
        "• `/start` - Start & get overview\n"
        "• `/new <title>` - Start a new analytics project\n"
        "• `/projects` - List your projects\n"
        "• `/status` - View current project state & files\n"
        "• `/learn` - Upload a methodology document to knowledge base\n"
        "• `/help` - Show this guide\n\n"
        "📎 *Uploading Data:*\n"
        "Attach any CSV, Excel, or PDF file to ingest and profile it.\n\n"
        "💬 *Asking Questions:*\n"
        "Ask any question to trigger autonomous Python analytics, velocity segmentation, stocking policies, or predictive modeling."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document uploads (CSVs, Excels, PDFs)."""
    if not update.effective_user or not update.message or not update.message.document:
        return

    doc = update.message.document
    filename = doc.file_name or "uploaded_file"
    caption = update.message.caption or ""

    if caption.strip().startswith("/learn"):
        await _handle_learn_document(update, context, doc, filename)
        return

    status_msg = await update.message.reply_text(f"⏳ Downloading and ingesting `{filename}`...", parse_mode="Markdown")

    user = await get_or_create_user(update.effective_user)
    project = await get_active_project_for_user(user.id)

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        file_bytes_io = BytesIO()
        await tg_file.download_to_memory(file_bytes_io)
        content_bytes = file_bytes_io.getvalue()

        async with async_session_factory() as db:
            project_file = await FileIngestionService.save_and_ingest_file(
                db=db,
                project_id=project.id,
                filename=filename,
                content_bytes=content_bytes,
            )

        summary_text = (
            f"✅ *File Ingested Successfully:*\n\n"
            f"• *Filename:* `{project_file.filename}`\n"
            f"• *Type:* `{project_file.file_type}`\n"
            f"• *Rows:* `{project_file.row_count or 'N/A'}` | *Columns:* `{project_file.column_count or 'N/A'}`\n"
            f"• *Project:* `{project.title}`\n"
        )
        await status_msg.edit_text(summary_text, parse_mode="Markdown")

        if caption:
            await _process_supervisor_message(
                update=update,
                context=context,
                user=user,
                project=project,
                user_text=f"I just uploaded `{filename}`. Context/Instruction: {caption}",
            )

    except Exception as e:
        logger.error(f"Error handling document: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Failed to ingest file: `{str(e)}`", parse_mode="Markdown")


async def _handle_learn_document(update: Update, context: ContextTypes.DEFAULT_TYPE, doc, filename: str) -> None:
    """Handle /learn domain document ingestion into Knowledge Base."""
    status_msg = await update.message.reply_text(f"🧠 Parsing `{filename}` into Global Knowledge Base...", parse_mode="Markdown")
    tg_file = await context.bot.get_file(doc.file_id)
    file_bytes_io = BytesIO()
    await tg_file.download_to_memory(file_bytes_io)
    content_bytes = file_bytes_io.getvalue()

    temp_dir = settings.PROJECTS_STORAGE_DIR / "_kb_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / FileIngestionService.sanitize_filename(filename)
    with open(temp_path, "wb") as f:
        f.write(content_bytes)

    try:
        extracted_text = FileIngestionService.extract_document_text(temp_path)
        async with async_session_factory() as db:
            kb_doc = KBDocument(
                source=filename,
                document_type=temp_path.suffix.lstrip("."),
                content=extracted_text[:100000],
                doc_metadata={"filename": filename, "length": len(extracted_text)},
            )
            db.add(kb_doc)
            await db.commit()

        await status_msg.edit_text(
            f"✅ *Knowledge Ingested:*\n\n• *Source:* `{filename}`\n• *Extracted Length:* `{len(extracted_text):,}` characters\n\nMethodology available to Supervisor and Data Scientist agents.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Failed to ingest knowledge document: `{e}`", parse_mode="Markdown")


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
    status_msg = await update.message.reply_text("🤔 *Analyzing and executing analytical tools...*", parse_mode="Markdown")

    project_dir = FileIngestionService.get_project_dir(project.id)
    charts_dir = project_dir / "charts"
    outputs_dir = project_dir / "outputs"

    # Pre-execution artifacts snapshot
    pre_charts = set(charts_dir.glob("*.png")) if charts_dir.exists() else set()
    pre_outputs = set(outputs_dir.glob("*.csv")) if outputs_dir.exists() else set()

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
        await status_msg.edit_text(reply_text, parse_mode="Markdown")

        # Check for newly generated charts and send as photos
        if charts_dir.exists():
            post_charts = set(charts_dir.glob("*.png"))
            new_charts = post_charts - pre_charts
            for chart_p in sorted(new_charts):
                with open(chart_p, "rb") as photo_f:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=photo_f,
                        caption=f"📈 Generated Chart: `{chart_p.name}`",
                    )

        # Check for newly generated action CSVs and send as documents
        if outputs_dir.exists():
            post_outputs = set(outputs_dir.glob("*.csv"))
            new_outputs = post_outputs - pre_outputs
            for out_p in sorted(new_outputs):
                with open(out_p, "rb") as doc_f:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=doc_f,
                        caption=f"📄 Generated Action Queue: `{out_p.name}`",
                    )

    except Exception as e:
        logger.error(f"Error in supervisor execution: {e}", exc_info=True)
        await status_msg.edit_text(f"⚠️ *Supervisor Error:* `{str(e)}`", parse_mode="Markdown")


def get_bot_app() -> Optional[Application]:
    """Build telegram application."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("new", new_project_command))
    app.add_handler(CommandHandler("projects", projects_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help", help_command))
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
