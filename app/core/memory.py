from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Conversation, Project, ProjectAssumption, ProjectDecision, ProjectFile, ProjectState


class ProjectMemoryManager:
    """Manages persistent structured analytical state for a project."""

    @staticmethod
    async def get_project_state(db: AsyncSession, project_id: str) -> Dict[str, Any]:
        """Fetch the full structured project state snapshot."""
        # Query project and state
        stmt = select(Project).where(Project.id == project_id)
        res = await db.execute(stmt)
        project = res.scalar_one_or_none()
        if not project:
            raise ValueError(f"Project with ID {project_id} not found.")

        state_stmt = select(ProjectState).where(ProjectState.project_id == project_id)
        state_res = await db.execute(state_stmt)
        state_obj = state_res.scalar_one_or_none()
        payload = state_obj.state_payload if state_obj else {}

        # Fetch files
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

        # Fetch decisions
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

        # Fetch assumptions
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
    """Manages chat conversation history."""

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
        # Return in chronological order
        return [
            {"role": r.role, "content": r.content, "created_at": r.created_at.isoformat()}
            for r in reversed(records)
        ]
