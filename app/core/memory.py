import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Conversation, Project, ProjectAssumption, ProjectDecision, ProjectFile, ProjectState

logger = logging.getLogger(__name__)


class ProjectMemoryManager:
    """Manages persistent structured analytical state for a project."""

    @staticmethod
    async def get_project_state(db: AsyncSession, project_id: str) -> Dict[str, Any]:
        """Fetch the full structured project state snapshot."""
        stmt = select(Project).where(Project.id == project_id)
        res = await db.execute(stmt)
        project = res.scalar_one_or_none()
        if not project:
            raise ValueError(f"Project with ID {project_id} not found.")

        state_stmt = select(ProjectState).where(ProjectState.project_id == project_id)
        state_res = await db.execute(state_stmt)
        state_obj = state_res.scalar_one_or_none()
        payload = state_obj.state_payload if state_obj else {}

        file_stmt = select(ProjectFile).where(ProjectFile.project_id == project_id)
        file_res = await db.execute(file_stmt)
        files = [
            {
                "id": f.id,
                "filename": f.filename,
                "file_type": f.file_type,
                "row_count": f.row_count,
                "column_count": f.column_count,
            }
            for f in file_res.scalars().all()
        ]

        dec_stmt = select(ProjectDecision).where(ProjectDecision.project_id == project_id)
        dec_res = await db.execute(dec_stmt)
        decisions = [
            {
                "decision": d.decision,
                "reason": d.reason,
                "status": d.status,
                "alternatives": d.alternatives,
            }
            for d in dec_res.scalars().all()
        ]

        ass_stmt = select(ProjectAssumption).where(ProjectAssumption.project_id == project_id)
        ass_res = await db.execute(ass_stmt)
        assumptions = [
            {
                "assumption": a.assumption,
                "rationale": a.rationale,
                "sensitivity_tier": a.sensitivity_tier,
                "status": a.status,
            }
            for a in ass_res.scalars().all()
        ]

        return {
            "project_id": project.id,
            "title": project.title,
            "objective": project.objective,
            "business_context": project.business_context,
            "current_phase": project.current_phase,
            "status": project.status,
            "iteration_count": project.iteration_count,
            "files": files,
            "decisions": decisions,
            "assumptions": assumptions,
            "payload": payload,
        }

    @staticmethod
    async def update_project_state(
        db: AsyncSession,
        project_id: str,
        state_updates: Dict[str, Any],
    ) -> None:
        """Update or insert structured project state snapshot."""
        stmt = select(ProjectState).where(ProjectState.project_id == project_id)
        res = await db.execute(stmt)
        state_obj = res.scalar_one_or_none()

        if state_obj:
            merged = {**state_obj.state_payload, **state_updates}
            state_obj.state_payload = merged
        else:
            state_obj = ProjectState(project_id=project_id, state_payload=state_updates)
            db.add(state_obj)

        await db.commit()


class ConversationMemoryManager:
    """Manages chat conversation history and hierarchical rolling checkpoint summarization."""

    @staticmethod
    async def add_message(
        db: AsyncSession,
        chat_id: int,
        role: str,
        content: str,
        project_id: Optional[str] = None,
    ) -> Conversation:
        """Record a chat message."""
        msg = Conversation(
            project_id=project_id,
            chat_id=chat_id,
            role=role,
            content=content,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg

    @staticmethod
    async def get_recent_messages(
        db: AsyncSession,
        chat_id: int,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent conversation history."""
        stmt = (
            select(Conversation)
            .where(Conversation.chat_id == chat_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        records = res.scalars().all()
        return [
            {"role": r.role, "content": r.content, "created_at": r.created_at.isoformat()}
            for r in reversed(records)
        ]

    @staticmethod
    async def get_context_with_rolling_checkpoints(
        db: AsyncSession,
        chat_id: int,
        project_id: Optional[str] = None,
        max_raw_turns: int = 6,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves context with Rolling Checkpoint Summarization:
        - If total messages <= max_raw_turns, returns all messages.
        - If total messages > max_raw_turns, compresses older messages into a compact rolling
          summary block and appends the latest raw turns to keep prompt token consumption lean.
        """
        stmt = (
            select(Conversation)
            .where(Conversation.chat_id == chat_id)
            .order_by(Conversation.created_at.asc())
        )
        res = await db.execute(stmt)
        all_msgs = res.scalars().all()

        if len(all_msgs) <= max_raw_turns:
            return [{"role": m.role, "content": m.content} for m in all_msgs]

        older_msgs = all_msgs[:-max_raw_turns]
        latest_msgs = all_msgs[-max_raw_turns:]

        # Compress older messages into bullet points
        summary_bullets = []
        for m in older_msgs[-8:]:  # Take window of older messages
            snippet = m.content[:150].replace("\n", " ").strip()
            summary_bullets.append(f"- [{m.role.upper()}]: {snippet}...")

        checkpoint_text = (
            "--- ROLLING CONVERSATION CHECKPOINT (Older Context) ---\n"
            + "\n".join(summary_bullets)
            + "\n------------------------------------------------------\n"
        )

        context = [{"role": "system", "content": checkpoint_text}]
        for m in latest_msgs:
            context.append({"role": m.role, "content": m.content})

        return context
