import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.models import ProjectFile


def _extract_pdf_pages_and_text(file_path: Path) -> Tuple[int, str]:
    """Helper to extract page count and text from PDF using PyPDF2 or PyMuPDF or fallback."""
    try:
        import PyPDF2
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            pages = len(reader.pages)
            text_blocks = [page.extract_text() or "" for page in reader.pages]
            return pages, "\n".join(text_blocks)
    except ImportError:
        pass

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(file_path))
        pages = len(doc)
        text_blocks = [page.get_text() for page in doc]
        return pages, "\n".join(text_blocks)
    except ImportError:
        pass

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        pages = len(reader.pages)
        text_blocks = [page.extract_text() or "" for page in reader.pages]
        return pages, "\n".join(text_blocks)
    except ImportError:
        pass

    return 1, "(PDF parser library not installed)"


class FileSecurityError(Exception):
    """Raised when an unsafe filename or path traversal attempt is detected."""
    pass


class FileIngestionService:
    """Handles secure file ingestion, parsing, and project-isolated storage."""

    ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".pdf", ".md", ".txt"}

    SUBDIRECTORIES = [
        "input",
        "raw",
        "cleaned",
        "working",
        "analysis",
        "charts",
        "models",
        "outputs",
        "logs",
        "state",
    ]

    @classmethod
    def get_project_dir(cls, project_id: str) -> Path:
        """Get the root directory for a given project."""
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", project_id)
        if not clean_id:
            raise FileSecurityError("Invalid project ID provided.")
        p_dir = (settings.PROJECTS_STORAGE_DIR / clean_id).resolve()
        return p_dir

    @classmethod
    def initialize_project_workspace(cls, project_id: str) -> Path:
        """Create the isolated directory hierarchy for a project."""
        p_dir = cls.get_project_dir(project_id)
        p_dir.mkdir(parents=True, exist_ok=True)
        for sub in cls.SUBDIRECTORIES:
            (p_dir / sub).mkdir(parents=True, exist_ok=True)
        return p_dir

    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """Strip directory traversal elements and special characters."""
        base_name = os.path.basename(filename)
        sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "_", base_name)
        if not sanitized or sanitized.startswith("."):
            sanitized = f"file_{sanitized}"
        return sanitized

    @classmethod
    async def save_and_ingest_file(
        cls,
        db: AsyncSession,
        project_id: str,
        filename: str,
        content_bytes: Optional[bytes] = None,
        file_bytes: Optional[bytes] = None,
    ) -> ProjectFile:
        """Save raw file bytes into project workspace and create a ProjectFile record."""
        raw_bytes = content_bytes if content_bytes is not None else file_bytes
        if raw_bytes is None:
            raise ValueError("No file content bytes provided.")

        p_dir = cls.initialize_project_workspace(project_id)
        safe_name = cls.sanitize_filename(filename)
        ext = Path(safe_name).suffix.lower()

        if ext not in cls.ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {ext}. Allowed: {cls.ALLOWED_EXTENSIONS}")

        if len(raw_bytes) > settings.MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File size ({len(raw_bytes)} bytes) exceeds maximum permitted ({settings.MAX_FILE_SIZE_BYTES} bytes)."
            )

        raw_target_path = p_dir / "raw" / safe_name
        with open(raw_target_path, "wb") as f:
            f.write(raw_bytes)

        # Inspect basic metadata
        row_count, col_count, schema_info = cls._inspect_file_metadata(raw_target_path, ext)

        file_record = ProjectFile(
            project_id=project_id,
            filename=safe_name,
            file_type=ext.lstrip("."),
            raw_path=str(raw_target_path),
            row_count=row_count,
            column_count=col_count,
            schema_info=schema_info,
        )
        db.add(file_record)
        await db.commit()
        await db.refresh(file_record)
        return file_record

    # Alias for backward compatibility
    save_uploaded_file = save_and_ingest_file

    @classmethod
    def _inspect_file_metadata(
        cls, file_path: Path, ext: str
    ) -> Tuple[Optional[int], Optional[int], Dict[str, Any]]:
        """Extract quick structural metadata without overwhelming memory."""
        try:
            if ext == ".csv":
                df = pd.read_csv(file_path, nrows=50)
                with open(file_path, "rb") as f:
                    row_count = max(0, sum(1 for _ in f) - 1)
                col_count = len(df.columns)
                schema_info = {col: str(dtype) for col, dtype in df.dtypes.items()}
                return row_count, col_count, schema_info

            elif ext in {".xlsx", ".xls"}:
                df = pd.read_excel(file_path, nrows=50)
                total_df = pd.read_excel(file_path)
                return len(total_df), len(total_df.columns), {col: str(dtype) for col, dtype in total_df.dtypes.items()}

            elif ext == ".json":
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return len(data), len(data[0].keys()) if data and isinstance(data[0], dict) else 1, {"type": "array"}
                elif isinstance(data, dict):
                    return len(data.keys()), 1, {"type": "object", "keys": list(data.keys())[:30]}
                return 1, 1, {"type": type(data).__name__}

            elif ext == ".pdf":
                page_count, _ = _extract_pdf_pages_and_text(file_path)
                return page_count, 1, {"pages": page_count, "type": "document"}

            elif ext in {".md", ".txt"}:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                return len(lines), 1, {"lines": len(lines), "type": "text"}

        except Exception as e:
            return None, None, {"error": str(e)}

        return None, None, {}

    @classmethod
    def extract_document_text(cls, file_path: Path) -> str:
        """Extract plain text from document formats (PDF, MD, TXT, JSON)."""
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            _, text = _extract_pdf_pages_and_text(file_path)
            return text
        elif ext in {".md", ".txt"}:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        elif ext == ".json":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        else:
            raise ValueError(f"Direct text extraction not supported for {ext}. Use dataframe parser.")

    @classmethod
    async def resolve_project_file(
        cls,
        db: AsyncSession,
        project_id: str,
        identifier: Optional[str],
    ) -> Optional[ProjectFile]:
        """
        Intelligently resolve a project file from either:
        1. Exact UUID (ProjectFile.id)
        2. Exact filename (case-insensitive)
        3. Filename substring (e.g. 'weekly_demand' -> 'weekly_demand.csv')
        4. Functional keywords (e.g. 'demand', 'lanes', 'warehouse', 'inventory', 'parts')
        """
        if not identifier or not str(identifier).strip():
            return None

        clean_id = str(identifier).strip()

        # 1. Exact ID
        stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == clean_id)
        res = await db.execute(stmt)
        f = res.scalar_one_or_none()
        if f:
            return f

        # 2. Exact filename (case-insensitive)
        stmt = select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.filename.ilike(clean_id),
        )
        res = await db.execute(stmt)
        f = res.scalar_one_or_none()
        if f:
            return f

        # 3. Filename without extension / substring
        raw_name = clean_id.lower().replace(".csv", "").replace(".xlsx", "").replace(".xls", "").replace(".json", "")
        stmt = select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.filename.ilike(f"%{raw_name}%"),
        )
        res = await db.execute(stmt)
        files = res.scalars().all()
        if files:
            return files[0]

        # 4. Inferred functional keyword matching
        keywords = ["demand", "lane", "transfer", "warehouse", "part", "item", "inventory", "stock", "cost"]
        for kw in keywords:
            if kw in raw_name:
                stmt = select(ProjectFile).where(
                    ProjectFile.project_id == project_id,
                    ProjectFile.filename.ilike(f"%{kw}%"),
                )
                res = await db.execute(stmt)
                match = res.scalars().first()
                if match:
                    return match

        return None

