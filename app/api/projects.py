from typing import Any, Dict, List, Optional
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Project, ProjectFile
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectSummary, ProjectStateSchema
from app.schemas.file import FileUploadResponse, FileProfileSummary
from app.tools.file_tools import FileIngestionService
from app.tools.profiling_tools import DatasetProfiler
from app.core.memory import ProjectMemoryManager
from app.agents.supervisor import SupervisorAgent

router = APIRouter()


class UserMessageRequest(BaseModel):
    message: str
    chat_id: Optional[int] = None


class AgentTurnResponse(BaseModel):
    project_id: str
    reply: str
    current_phase: str
    status: str
    tool_calls: List[Dict[str, Any]]
    execution_time_ms: float


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create a new isolated analytics project."""
    project = Project(
        title=payload.title,
        objective=payload.objective,
        business_context=payload.business_context,
        user_id=payload.user_id,
        current_phase="INITIALIZED",
        status="ACTIVE",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    # Initialize filesystem workspace
    FileIngestionService.initialize_project_workspace(project.id)

    # Initialize empty state snapshot
    await ProjectMemoryManager.update_project_state(
        db=db,
        project_id=project.id,
        state_updates={
            "project_id": project.id,
            "title": project.title,
            "objective": project.objective,
            "business_context": project.business_context,
            "current_phase": project.current_phase,
            "status": project.status,
            "datasets": [],
            "assumptions": [],
            "decisions": [],
            "recommendations": [],
            "artifacts": [],
        },
    )

    return project


@router.get("", response_model=List[ProjectResponse])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects."""
    stmt = select(Project).order_by(Project.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get project by ID."""
    stmt = select(Project).where(Project.id == project_id)
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@router.get("/{project_id}/state")
async def get_project_full_state(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get structured project state and history."""
    try:
        return await ProjectMemoryManager.get_project_state(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{project_id}/message", response_model=AgentTurnResponse)
async def send_project_message(
    project_id: str,
    payload: UserMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run an autonomous reasoning turn with the Supervisor Agent for this project."""
    stmt = select(Project).where(Project.id == project_id)
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    supervisor = SupervisorAgent()
    agent_res = await supervisor.execute_turn(
        db=db,
        project_id=project_id,
        user_message=payload.message,
        chat_id=payload.chat_id,
    )

    # Refresh project to get updated state/phase
    await db.refresh(project)

    return AgentTurnResponse(
        project_id=project_id,
        reply=agent_res.content,
        current_phase=project.current_phase,
        status=project.status,
        tool_calls=[tc.model_dump() for tc in agent_res.tool_calls],
        execution_time_ms=agent_res.execution_time_ms,
    )


@router.post("/{project_id}/files", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file_to_project(
    project_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload and ingest a file into an isolated project workspace."""
    stmt = select(Project).where(Project.id == project_id)
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    content = await file.read()
    try:
        file_record = await FileIngestionService.save_and_ingest_file(
            db=db,
            project_id=project_id,
            filename=file.filename or "uploaded_file",
            content_bytes=content,
        )
        return FileUploadResponse(
            file_id=file_record.id,
            project_id=file_record.project_id,
            filename=file_record.filename,
            file_type=file_record.file_type,
            raw_path=file_record.raw_path,
            row_count=file_record.row_count,
            column_count=file_record.column_count,
            created_at=file_record.created_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}/files")
async def list_project_files(project_id: str, db: AsyncSession = Depends(get_db)):
    """List all ingested files for a project."""
    stmt = select(ProjectFile).where(ProjectFile.project_id == project_id)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("/{project_id}/files/{file_id}/profile", response_model=FileProfileSummary)
async def profile_project_file(
    project_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Run deterministic statistical data profiling on a tabular project file."""
    stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == file_id)
    res = await db.execute(stmt)
    file_record = res.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found in project")

    raw_path = Path(file_record.raw_path)
    if not raw_path.exists():
        raise HTTPException(status_code=404, detail="Raw file does not exist on disk")

    try:
        summary = DatasetProfiler.profile_tabular_file(raw_path, file_id=file_record.id)
        return summary
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
