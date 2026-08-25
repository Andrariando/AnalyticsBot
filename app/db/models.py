import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.orm import DeclarativeBase, relationship

try:
    from sqlalchemy.dialects.postgresql import JSONB
    JSON_TYPE = JSONB().with_variant(SQLiteJSON, "sqlite")
except ImportError:
    JSON_TYPE = SQLiteJSON


class Base(DeclarativeBase):
    """Base model class."""
    pass


def generate_uuid() -> str:
    return str(uuid.uuid4())


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    telegram_id = Column(BigInteger, unique=True, nullable=True, index=True)
    username = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=True)
    business_context = Column(JSON_TYPE, default=dict)
    current_phase = Column(String(50), nullable=False, default="INITIALIZED")
    status = Column(String(50), nullable=False, default="ACTIVE")
    iteration_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)
    updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)

    user = relationship("User", back_populates="projects")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    state = relationship("ProjectState", back_populates="project", uselist=False, cascade="all, delete-orphan")
    assumptions = relationship("ProjectAssumption", back_populates="project", cascade="all, delete-orphan")
    decisions = relationship("ProjectDecision", back_populates="project", cascade="all, delete-orphan")
    quality_issues = relationship("DataQualityIssue", back_populates="project", cascade="all, delete-orphan")
    model_runs = relationship("ModelRun", back_populates="project", cascade="all, delete-orphan")
    critic_reviews = relationship("CriticReview", back_populates="project", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="project", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="project", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="project", cascade="all, delete-orphan")


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    raw_path = Column(Text, nullable=False)
    cleaned_path = Column(Text, nullable=True)
    row_count = Column(Integer, nullable=True)
    column_count = Column(Integer, nullable=True)
    schema_info = Column(JSON_TYPE, default=dict)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="files")


class ProjectState(Base):
    __tablename__ = "project_state"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    state_payload = Column(JSON_TYPE, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)

    project = relationship("Project", back_populates="state")


class ProjectAssumption(Base):
    __tablename__ = "project_assumptions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assumption = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    sensitivity_tier = Column(String(50), default="MODERATELY_SENSITIVE")
    status = Column(String(50), default="ACTIVE")
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="assumptions")


class ProjectDecision(Base):
    __tablename__ = "project_decisions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    decision = Column(Text, nullable=False)
    alternatives = Column(JSON_TYPE, default=list)
    reason = Column(Text, nullable=False)
    validation_evidence = Column(Text, nullable=True)
    risk_assessment = Column(Text, nullable=True)
    status = Column(String(50), default="APPROVED")
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="decisions")


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String(36), ForeignKey("project_files.id", ondelete="SET NULL"), nullable=True)
    check_name = Column(String(255), nullable=False)
    severity = Column(String(50), nullable=False)  # CRITICAL, MATERIAL, MINOR
    details = Column(JSON_TYPE, nullable=False, default=dict)
    treatment_applied = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="quality_issues")


class ModelRun(Base):
    __tablename__ = "model_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    model_name = Column(String(255), nullable=False)
    version = Column(String(50), nullable=False)
    problem_type = Column(String(50), nullable=False)  # FORECAST, CLASSIFICATION, OPTIMIZATION
    target_variable = Column(String(255), nullable=True)
    baseline_metrics = Column(JSON_TYPE, nullable=False, default=dict)
    model_metrics = Column(JSON_TYPE, nullable=False, default=dict)
    artifact_path = Column(Text, nullable=True)
    status = Column(String(50), nullable=False)  # ACTIVE, CANDIDATE, SUPERSEDED, REJECTED
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="model_runs")


class CriticReview(Base):
    __tablename__ = "critic_reviews"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    iteration = Column(Integer, nullable=False, default=1)
    perspective = Column(String(50), nullable=False)  # BUSINESS, TECHNICAL
    overall_status = Column(String(50), nullable=False)  # ACCEPT, REVISE, REJECT
    issues = Column(JSON_TYPE, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="critic_reviews")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = Column(Integer, nullable=False)
    entity = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    segment = Column(String(50), nullable=True)
    problem = Column(Text, nullable=False)
    recommended_action = Column(String(100), nullable=False)  # HOLD, BUY, REBALANCE, DISPOSE, etc.
    quantity = Column(Numeric(14, 4), nullable=True)
    timing = Column(String(100), nullable=True)
    financial_impact = Column(JSON_TYPE, nullable=False, default=dict)
    operational_impact = Column(Text, nullable=True)
    service_impact = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    human_review_required = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="recommendations")


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_type = Column(String(100), nullable=False)  # MEMO, REPORT, EXCEL, NOTEBOOK, CHART
    file_path = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="artifacts")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String(50), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    project = relationship("Project", back_populates="conversations")


class KBDocument(Base):
    __tablename__ = "kb_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    source = Column(String(255), nullable=False)
    document_type = Column(String(50), nullable=True)
    content = Column(Text, nullable=False)
    doc_metadata = Column(JSON_TYPE, default=dict)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)
