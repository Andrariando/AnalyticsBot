from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class FileUploadResponse(BaseModel):
    file_id: str
    project_id: str
    filename: str
    file_type: str
    raw_path: str
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    null_count: int
    null_percentage: float
    unique_count: int
    sample_values: List[Any] = Field(default_factory=list)
    numeric_stats: Optional[Dict[str, float]] = None
    is_key_candidate: bool = False


class FileProfileSummary(BaseModel):
    file_id: str
    filename: str
    row_count: int
    column_count: int
    columns: List[ColumnProfile]
    duplicate_rows_count: int
    date_coverage: Optional[Dict[str, Any]] = None
    potential_grain: List[str] = Field(default_factory=list)
    quality_alerts: List[str] = Field(default_factory=list)


class DataQualityIssueSchema(BaseModel):
    id: Optional[str] = None
    project_id: str
    file_id: Optional[str] = None
    check_name: str
    severity: str  # CRITICAL, MATERIAL, MINOR
    details: Dict[str, Any]
    treatment_applied: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
