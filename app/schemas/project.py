from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    title: str = Field(..., description="Project title")
    objective: Optional[str] = Field(default=None, description="Analytical objective and problem statement")
    business_context: Dict[str, Any] = Field(default_factory=dict, description="Contextual constraints and parameters")
    user_id: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    title: str
    objective: Optional[str] = None
    business_context: Dict[str, Any] = Field(default_factory=dict)
    current_phase: str
    status: str
    iteration_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectSummary(BaseModel):
    id: str
    title: str
    current_phase: str
    status: str
    file_count: int
    decision_count: int
    recommendation_count: int
    created_at: datetime


class ProjectStateSchema(BaseModel):
    project_id: str
    title: str
    objective: Optional[str] = None
    business_context: Dict[str, Any] = Field(default_factory=dict)
    stakeholders: List[str] = Field(default_factory=list)
    time_horizon: Optional[str] = None
    datasets: List[Dict[str, Any]] = Field(default_factory=list)
    data_dictionary: Dict[str, Any] = Field(default_factory=dict)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality_issues: List[Dict[str, Any]] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    methodology: Dict[str, Any] = Field(default_factory=dict)
    completed_steps: List[str] = Field(default_factory=list)
    models: List[Dict[str, Any]] = Field(default_factory=list)
    critic_reviews: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    current_phase: str = "INITIALIZED"
    status: str = "ACTIVE"
