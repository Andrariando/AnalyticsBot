from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """System-wide configuration settings loaded from environment variables and .env file."""

    # Project Root Directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None, description="Telegram Bot Token from @BotFather")

    # LLM API Keys
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API Key")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API Key")

    # Models
    SUPERVISOR_MODEL: str = Field(default="gpt-4o", description="Model for Supervisor Agent")
    DATA_SCIENTIST_MODEL: str = Field(default="gpt-4o", description="Model for Data Scientist Agent")
    CRITIC_MODEL: str = Field(default="gpt-4o", description="Model for Critic Agent")
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small", description="Embedding model for Knowledge Base")

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./analytics_os.db",
        description="Async Database connection URL (Postgres or SQLite)",
    )

    # Server Settings
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Project Storage
    PROJECTS_STORAGE_DIR: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "projects",
        description="Root storage path for project files",
    )
    MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

# Ensure projects storage directory exists
settings.PROJECTS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
