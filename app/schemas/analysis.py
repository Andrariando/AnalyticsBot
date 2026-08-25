from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class AssumptionCreate(BaseModel):
    assumption: str
    rationale: Optional[str] = None
    sensitivity_tier: str = "MODERATELY_SENSITIVE"  # ROBUST, MODERATELY_SENSITIVE, FRAGILE


class DecisionCreate(BaseModel):
    decision: str
    alternatives: List[str] = Field(default_factory=list)
    reason: str
    validation_evidence: Optional[str] = None
    risk_assessment: Optional[str] = None
    status: str = "APPROVED"


class ModelRunSchema(BaseModel):
    id: Optional[str] = None
    project_id: str
    model_name: str
    version: str
    problem_type: str
    target_variable: Optional[str] = None
    baseline_metrics: Dict[str, Any]
    model_metrics: Dict[str, Any]
    artifact_path: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CriticIssue(BaseModel):
    severity: str  # CRITICAL, MATERIAL, MINOR
    perspective: str  # BUSINESS, TECHNICAL
    issue: str
    why_it_matters: str
    required_validation: str


class CriticReviewSchema(BaseModel):
    id: Optional[str] = None
    project_id: str
    iteration: int = 1
    perspective: str
    overall_status: str  # ACCEPT, REVISE, REJECT
    issues: List[CriticIssue] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class FinancialImpact(BaseModel):
    category: str  # WORKING_CAPITAL_RELEASED, HOLDING_COST_SAVINGS, CASH_RECOVERED, PURCHASE_AVOIDED, PURCHASE_DEFERRED, PL_SAVINGS, WRITE_OFF
    amount: float
    currency: str = "USD"
    time_horizon_weeks: Optional[int] = None
    confidence_level: Optional[float] = None
    notes: Optional[str] = None


class RecommendationSchema(BaseModel):
    id: Optional[str] = None
    project_id: str
    priority: int
    entity: str
    location: Optional[str] = None
    segment: Optional[str] = None
    problem: str
    recommended_action: str  # HOLD, BUY, STOP_REPLENISHMENT, CHANGE_PARAMETER, EXPEDITE, TRANSFER, RETURN, LIQUIDATE, SCRAP, etc.
    quantity: Optional[float] = None
    timing: Optional[str] = None
    financial_impact: FinancialImpact
    operational_impact: Optional[str] = None
    service_impact: Optional[str] = None
    confidence: Optional[float] = None
    human_review_required: bool = False
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ArtifactSchema(BaseModel):
    id: Optional[str] = None
    project_id: str
    artifact_type: str  # MEMO, REPORT, EXCEL, NOTEBOOK, CHART
    file_path: str
    summary: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
