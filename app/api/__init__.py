from fastapi import APIRouter
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.artifacts import router as artifacts_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(projects_router, prefix="/projects", tags=["Projects"])
api_router.include_router(artifacts_router, prefix="/projects", tags=["Artifacts"])
