import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.base_agent import BaseAgent, ToolDefinition, AgentResponse
from app.agents.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT
from app.config import settings
from app.db.models import Project, ProjectAssumption, ProjectDecision, ProjectFile, KBDocument
from app.core.state_machine import ProjectStateMachine, ProjectPhase, StateTransitionError
from app.core.memory import ProjectMemoryManager, ConversationMemoryManager
from app.tools.file_tools import FileIngestionService
from app.tools.profiling_tools import DatasetProfiler
from app.tools.runtime import PythonAnalyticsRuntime
from app.tools.cleaning_tools import DataCleaningService
from app.tools.visualization_tools import ChartGenerationTool

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """
    Supervisor Agent responsible for analytical framing, project orchestration,
    and synthesis with economic discipline.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.SUPERVISOR_MODEL

    async def execute_turn(
        self,
        db: AsyncSession,
        project_id: str,
        user_message: str,
        chat_id: Optional[int] = None,
    ) -> AgentResponse:
        """
        Executes an autonomous turn for a given project.
        """
        state_data = await ProjectMemoryManager.get_project_state(db, project_id)

        history_messages: List[Dict[str, Any]] = []
        if chat_id:
            raw_history = await ConversationMemoryManager.get_recent_messages(db, chat_id=chat_id, limit=8)
            history_messages = [{"role": m["role"], "content": m["content"]} for m in raw_history]

        history_messages.append({"role": "user", "content": user_message})

        if chat_id:
            await ConversationMemoryManager.add_message(
                db=db,
                chat_id=chat_id,
                role="user",
                content=user_message,
                project_id=project_id,
            )

        project_context_header = (
            f"--- CURRENT PROJECT CONTEXT ---\n"
            f"Project ID: {project_id}\n"
            f"Title: {state_data.get('title')}\n"
            f"Current Phase: {state_data.get('current_phase')}\n"
            f"Status: {state_data.get('status')}\n"
            f"Ingested Datasets: {[f['filename'] for f in state_data.get('files', [])]}\n"
            f"Logged Assumptions: {len(state_data.get('assumptions', []))}\n"
            f"Logged Decisions: {len(state_data.get('decisions', []))}\n"
            f"--------------------------------\n"
        )

        messages_for_turn = [
            {"role": "system", "content": project_context_header}
        ] + history_messages

        tools = self._build_supervisor_tools(db=db, project_id=project_id)
        agent = BaseAgent(
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            model_name=self.model_name,
            tools=tools,
            max_iterations=10,
        )

        response = await agent.run_turn(messages=messages_for_turn)

        if chat_id:
            await ConversationMemoryManager.add_message(
                db=db,
                chat_id=chat_id,
                role="assistant",
                content=response.content,
                project_id=project_id,
            )

        return response

    def _build_supervisor_tools(self, db: AsyncSession, project_id: str) -> List[ToolDefinition]:
        """Construct the supervisor's active tool palette bound to the current database session and project."""

        async def inspect_project_files() -> Dict[str, Any]:
            """Inspect all files uploaded to the current project."""
            stmt = select(ProjectFile).where(ProjectFile.project_id == project_id)
            res = await db.execute(stmt)
            files = res.scalars().all()
            return {
                "project_id": project_id,
                "file_count": len(files),
                "files": [
                    {
                        "file_id": f.id,
                        "filename": f.filename,
                        "file_type": f.file_type,
                        "row_count": f.row_count,
                        "column_count": f.column_count,
                        "cleaned_path": f.cleaned_path,
                        "schema": f.schema_info,
                    }
                    for f in files
                ],
            }

        async def profile_dataset(file_id: str, rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
            """Run deterministic statistical profiling on an ingested tabular dataset."""
            stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == file_id)
            res = await db.execute(stmt)
            file_rec = res.scalar_one_or_none()
            if not file_rec:
                return {"error": f"File with ID {file_id} not found in project."}

            file_path = Path(file_rec.cleaned_path or file_rec.raw_path)
            if not file_path.exists():
                return {"error": f"File path {file_path} not found on disk."}

            summary = DatasetProfiler.profile_tabular_file(
                file_path=file_path,
                file_id=file_rec.id,
                business_rules=rules,
            )
            return summary.model_dump()

        async def clean_dataset(file_id: str) -> Dict[str, Any]:
            """Clean dataset while preserving raw values and registering quality flags."""
            return await DataCleaningService.clean_tabular_dataset(db=db, project_id=project_id, file_id=file_id)

        async def run_python_analysis(code_string: str, script_name: str = "analysis.py") -> Dict[str, Any]:
            """Execute sandboxed Python analysis script in the project workspace."""
            res = await PythonAnalyticsRuntime.execute_code(
                project_id=project_id,
                code_string=code_string,
                script_name=script_name,
            )
            return res.model_dump()

        async def generate_pareto_chart(
            file_id: str,
            sku_col: str = "sku",
            dollar_col: str = "dollar_volume",
            unit_col: Optional[str] = "unit_volume",
        ) -> Dict[str, Any]:
            """Generate a Pareto velocity concentration curve."""
            stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == file_id)
            res = await db.execute(stmt)
            file_rec = res.scalar_one_or_none()
            if not file_rec:
                return {"error": f"File {file_id} not found."}
            df = pd.read_csv(file_rec.cleaned_path or file_rec.raw_path)
            return await ChartGenerationTool.create_pareto_chart(
                db=db,
                project_id=project_id,
                df_skus=df,
                sku_col=sku_col,
                dollar_col=dollar_col,
                unit_col=unit_col,
            )

        async def log_assumption(
            assumption: str,
            rationale: Optional[str] = None,
            sensitivity_tier: str = "MODERATELY_SENSITIVE",
        ) -> Dict[str, Any]:
            """Record an explicit, auditable analytical assumption."""
            ass_rec = ProjectAssumption(
                project_id=project_id,
                assumption=assumption,
                rationale=rationale,
                sensitivity_tier=sensitivity_tier,
                status="ACTIVE",
            )
            db.add(ass_rec)
            await db.commit()
            await db.refresh(ass_rec)
            return {
                "status": "logged",
                "assumption_id": ass_rec.id,
                "assumption": ass_rec.assumption,
            }

        async def log_decision(
            decision: str,
            reason: str,
            alternatives: Optional[List[str]] = None,
            risk_assessment: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Record an explicit, auditable methodological or business decision."""
            dec_rec = ProjectDecision(
                project_id=project_id,
                decision=decision,
                reason=reason,
                alternatives=alternatives or [],
                risk_assessment=risk_assessment,
                status="APPROVED",
            )
            db.add(dec_rec)
            await db.commit()
            await db.refresh(dec_rec)
            return {
                "status": "logged",
                "decision_id": dec_rec.id,
                "decision": dec_rec.decision,
            }

        async def update_project_framing(
            objective: Optional[str] = None,
            target_decision: Optional[str] = None,
            stakeholders: Optional[List[str]] = None,
            constraints: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Update high-level problem statement, target decision, and constraints."""
            updates: Dict[str, Any] = {}
            if objective:
                updates["objective"] = objective
            if target_decision:
                updates["target_decision"] = target_decision
            if stakeholders:
                updates["stakeholders"] = stakeholders
            if constraints:
                updates["constraints"] = constraints

            await ProjectMemoryManager.update_project_state(db=db, project_id=project_id, state_updates=updates)

            if objective:
                stmt = select(Project).where(Project.id == project_id)
                res = await db.execute(stmt)
                p = res.scalar_one_or_none()
                if p:
                    p.objective = objective
                    await db.commit()

            return {"status": "updated", "framing": updates}

        async def advance_project_phase(target_phase: str) -> Dict[str, Any]:
            """Advance the state machine to the next analytical phase."""
            stmt = select(Project).where(Project.id == project_id)
            res = await db.execute(stmt)
            project = res.scalar_one_or_none()
            if not project:
                return {"error": "Project not found"}

            try:
                curr_p = ProjectPhase(project.current_phase)
                tgt_p = ProjectPhase(target_phase.upper())
                new_phase, new_status, new_iters = ProjectStateMachine.transition(
                    current_phase=curr_p,
                    target_phase=tgt_p,
                    iteration_count=project.iteration_count,
                )
                project.current_phase = new_phase.value
                project.status = new_status.value
                project.iteration_count = new_iters
                await db.commit()
                return {
                    "status": "transitioned",
                    "previous_phase": curr_p.value,
                    "current_phase": new_phase.value,
                    "project_status": new_status.value,
                }
            except (ValueError, StateTransitionError) as e:
                return {"error": str(e)}

        async def search_knowledge_base(query: str) -> Dict[str, Any]:
            """Search the global curated knowledge base of analytical methodologies and literature."""
            stmt = select(KBDocument).order_by(KBDocument.created_at.desc()).limit(3)
            res = await db.execute(stmt)
            docs = res.scalars().all()
            return {
                "query": query,
                "results": [
                    {
                        "source": d.source,
                        "document_type": d.document_type,
                        "snippet": d.content[:500],
                    }
                    for d in docs
                ],
            }

        return [
            ToolDefinition(
                name="inspect_project_files",
                description="List all uploaded files, row counts, column counts, and schemas in the project workspace.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=inspect_project_files,
            ),
            ToolDefinition(
                name="profile_dataset",
                description="Run deterministic statistical and structural data profiling on a tabular dataset. Returns rows, columns, null rates, key candidates, and quality alerts.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "The unique ID of the file to profile."},
                        "rules": {
                            "type": "array",
                            "description": "Optional custom business rule expressions to validate.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "expression": {"type": "string"},
                                    "columns": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["name", "expression"],
                            },
                        },
                    },
                    "required": ["file_id"],
                    "additionalProperties": False,
                },
                handler=profile_dataset,
            ),
            ToolDefinition(
                name="clean_dataset",
                description="Clean tabular dataset while preserving raw values, capping fulfillment anomalies, clipping negative inventories, and logging data quality issues.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "The unique ID of the file to clean."}
                    },
                    "required": ["file_id"],
                    "additionalProperties": False,
                },
                handler=clean_dataset,
            ),
            ToolDefinition(
                name="run_python_analysis",
                description="Execute a sandboxed Python analysis script in the project workspace. Code can access environment variables RAW_DIR, CLEANED_DIR, ANALYSIS_DIR, CHARTS_DIR, OUTPUTS_DIR.",
                parameters={
                    "type": "object",
                    "properties": {
                        "code_string": {"type": "string", "description": "Complete Python script to execute."},
                        "script_name": {"type": "string", "description": "Filename to save the script under."},
                    },
                    "required": ["code_string"],
                    "additionalProperties": False,
                },
                handler=run_python_analysis,
            ),
            ToolDefinition(
                name="generate_pareto_chart",
                description="Generate a high-resolution Pareto concentration chart comparing cumulative dollar volume vs unit volume.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "File containing SKU volumes."},
                        "sku_col": {"type": "string", "description": "Column name for SKU/part number."},
                        "dollar_col": {"type": "string", "description": "Column name for dollar demand."},
                        "unit_col": {"type": "string", "description": "Column name for unit demand."},
                    },
                    "required": ["file_id", "sku_col", "dollar_col"],
                    "additionalProperties": False,
                },
                handler=generate_pareto_chart,
            ),
            ToolDefinition(
                name="log_assumption",
                description="Record an explicit, auditable analytical assumption in project memory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "assumption": {"type": "string", "description": "The assumption being made."},
                        "rationale": {"type": "string", "description": "Why this assumption is justifiable."},
                        "sensitivity_tier": {
                            "type": "string",
                            "enum": ["ROBUST", "MODERATELY_SENSITIVE", "FRAGILE"],
                            "description": "Estimated sensitivity of project outcomes to this assumption.",
                        },
                    },
                    "required": ["assumption"],
                    "additionalProperties": False,
                },
                handler=log_assumption,
            ),
            ToolDefinition(
                name="log_decision",
                description="Record an explicit, auditable methodological or business decision in project memory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string", "description": "The decision made."},
                        "reason": {"type": "string", "description": "Analytical rationale for this decision."},
                        "alternatives": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Alternative options considered.",
                        },
                        "risk_assessment": {"type": "string", "description": "Operational or analytical risk."},
                    },
                    "required": ["decision", "reason"],
                    "additionalProperties": False,
                },
                handler=log_decision,
            ),
            ToolDefinition(
                name="update_project_framing",
                description="Update the structured framing, target decision, stakeholders, and constraints of the project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "objective": {"type": "string", "description": "Refined problem objective."},
                        "target_decision": {"type": "string", "description": "The specific operational decision."},
                        "stakeholders": {"type": "array", "items": {"type": "string"}},
                        "constraints": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                handler=update_project_framing,
            ),
            ToolDefinition(
                name="advance_project_phase",
                description="Advance the project state machine to the next valid analytical phase.",
                parameters={
                    "type": "object",
                    "properties": {
                        "target_phase": {
                            "type": "string",
                            "enum": [
                                "PROBLEM_FRAMED",
                                "DATA_PROFILED",
                                "METHOD_SELECTED",
                                "ANALYSIS_COMPLETE",
                                "TECHNICAL_REVIEW",
                                "BUSINESS_REVIEW",
                                "VALIDATED",
                                "DOCUMENTATION",
                                "COMPLETE",
                            ],
                            "description": "The target phase to transition into.",
                        }
                    },
                    "required": ["target_phase"],
                    "additionalProperties": False,
                },
                handler=advance_project_phase,
            ),
            ToolDefinition(
                name="search_knowledge_base",
                description="Search the global knowledge base of modeling techniques and methodologies.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Semantic search query."}
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=search_knowledge_base,
            ),
        ]
