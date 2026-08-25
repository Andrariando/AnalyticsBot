import asyncio
import os
import shutil
import pytest
import pytest_asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.db.models import Base
from app.config import settings

# Test database
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
test_session_factory = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create fresh in-memory database session for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="session", autouse=True)
def clean_test_projects():
    """Cleanup temporary project directories after testing."""
    test_storage = settings.PROJECTS_STORAGE_DIR / "_test_workspace"
    test_storage.mkdir(parents=True, exist_ok=True)
    yield test_storage
    if test_storage.exists():
        shutil.rmtree(test_storage, ignore_errors=True)
