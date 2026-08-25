from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db.session import init_db
from app.api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to initialize resources."""
    await init_db()
    yield


app = FastAPI(
    title="Autonomous Business Analytics Operating System",
    description="Enterprise Multi-Agent Analytics Platform with Deterministic Python Runtime and State Machine Quality Gates",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "system": "Autonomous Business Analytics Operating System",
        "status": "operational",
        "docs": "/docs",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)
