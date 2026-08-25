from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Artifact

router = APIRouter()


@router.get("/{project_id}/artifacts")
async def list_artifacts(project_id: str, db: AsyncSession = Depends(get_db)):
    """List all deliverables and artifacts for a project."""
    stmt = select(Artifact).where(Artifact.project_id == project_id)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/{project_id}/artifacts/{artifact_id}/download")
async def download_artifact(project_id: str, artifact_id: str, db: AsyncSession = Depends(get_db)):
    """Download an artifact file."""
    stmt = select(Artifact).where(Artifact.project_id == project_id, Artifact.id == artifact_id)
    res = await db.execute(stmt)
    artifact = res.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    file_path = Path(artifact.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file does not exist on disk")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )
