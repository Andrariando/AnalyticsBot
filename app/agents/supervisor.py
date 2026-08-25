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
from app.tools.supply_chain import SupplyChainAnalyticsService
from app.tools.modeling import PredictiveModelingService
from app.tools.reporting import ReportingService
from app.tools.notebook_tools import JupyterNotebookBuilder
from app.tools.multi_echelon import MultiEchelonAnalyticsService
from app.agents.critic import CriticAgent
from app.agents.task_runner import ParallelTaskRunner

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
        Executes an autonomous turn for a given project with rolling checkpoint summarization.
        """
        state_data = await ProjectMemoryManager.get_project_state(db, project_id)

        history_messages: List[Dict[str, Any]] = []
        if chat_id:
            # Use Rolling Checkpoint Summarization to prevent prompt token bloat
            history_messages = await ConversationMemoryManager.get_context_with_rolling_checkpoints(
                db=db,
                chat_id=chat_id,
                project_id=project_id,
                max_raw_turns=6,
            )

        history_messages.append({"role": "user", "content": user_message})

        if chat_id:
            await ConversationMemoryManager.add_message(
                db=db,
                chat_id=chat_id,
                role="user",
                content=user_message,
                project_id=project_id,
            )

        files_info = []
        for f in state_data.get("files", []):
            files_info.append(
                f"• {f['filename']} (ID: `{f['id']}`, type: {f.get('file_type', 'CSV')}, rows: {f.get('row_count', 'N/A')})"
            )
        files_str = "\n".join(files_info) if files_info else "None uploaded yet"

        project_context_header = (
            f"--- CURRENT PROJECT CONTEXT ---\n"
            f"Project ID: {project_id}\n"
            f"Title: {state_data.get('title')}\n"
            f"Current Phase: {state_data.get('current_phase')}\n"
            f"Status: {state_data.get('status')}\n\n"
            f"Ingested Datasets:\n{files_str}\n\n"
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
            """Run deterministic statistical profiling on an ingested tabular dataset (accepts UUID or filename)."""
            file_rec = await FileIngestionService.resolve_project_file(db, project_id, file_id)
            if not file_rec:
                stmt = select(ProjectFile).where(ProjectFile.project_id == project_id)
                res = await db.execute(stmt)
                avail = [f.filename for f in res.scalars().all()]
                return {"error": f"File '{file_id}' not found in project. Available files: {avail}"}

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
            """Clean dataset while preserving raw values and registering quality flags (accepts UUID or filename)."""
            file_rec = await FileIngestionService.resolve_project_file(db, project_id, file_id)
            if not file_rec:
                return {"error": f"File '{file_id}' not found in project."}
            return await DataCleaningService.clean_tabular_dataset(db=db, project_id=project_id, file_id=file_rec.id)

        async def calculate_velocity_segmentation(
            demand_file_id: str,
            parts_file_id: Optional[str] = None,
            demand_window_weeks: int = 26,
        ) -> Dict[str, Any]:
            """Compute ABC (Dollar & Unit), XYZ, ADI, CV2, and Syntetos-Boylan demand segmentation."""
            return await SupplyChainAnalyticsService.calculate_velocity_segmentation(
                db=db,
                project_id=project_id,
                demand_file_id=demand_file_id,
                parts_file_id=parts_file_id,
                demand_window_weeks=demand_window_weeks,
            )

        async def calculate_stocking_policy(
            inventory_file_id: str,
            demand_file_id: str,
            parts_file_id: Optional[str] = None,
            warehouses_file_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Calculate dynamic Safety Stock, ROP, Order-Up-To, Target WOS, and Excess/Shortages."""
            return await SupplyChainAnalyticsService.calculate_stocking_policy(
                db=db,
                project_id=project_id,
                inventory_file_id=inventory_file_id,
                demand_file_id=demand_file_id,
                parts_file_id=parts_file_id,
                warehouses_file_id=warehouses_file_id,
            )

        async def calculate_multi_echelon_policy(
            demand_file_id: str,
            central_dc_code: str = "CDC",
            target_service_level: float = 0.95,
        ) -> Dict[str, Any]:
            """Compute Multi-Echelon MEIO inventory optimization (Hub-and-Spoke risk pooling and echelon buffer sizing)."""
            return await MultiEchelonAnalyticsService.calculate_multi_echelon_policy(
                db=db,
                project_id=project_id,
                demand_file_id=demand_file_id,
                central_dc_code=central_dc_code,
                target_service_level=target_service_level,
            )

        async def generate_rebalance_candidates(
            transfer_lanes_file_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Generate multi-DC lateral inventory transfer queue using exact Google OR-Tools MILP optimization."""
            return await SupplyChainAnalyticsService.generate_rebalance_candidates(
                db=db,
                project_id=project_id,
                transfer_lanes_file_id=transfer_lanes_file_id,
            )

        async def generate_disposition_candidates() -> Dict[str, Any]:
            """Generate disposition action queue (Vendor Returns for contract-eligible items, Liquidation, or Scrap)."""
            return await SupplyChainAnalyticsService.generate_disposition_candidates(
                db=db,
                project_id=project_id,
            )

        async def run_python_analysis(code_string: str, script_name: str = "analysis.py") -> Dict[str, Any]:
            """Execute arbitrary custom Python analysis script in sandboxed project runtime."""
            res = await PythonAnalyticsRuntime.execute_code(
                project_id=project_id,
                code_string=code_string,
                script_name=script_name,
            )
            return res.model_dump()

        async def create_custom_jupyter_notebook(
            title: str,
            sections: List[Dict[str, Any]],
            filename: str = "custom_analysis.ipynb",
        ) -> Dict[str, Any]:
            """Compile an interactive, commented Jupyter Notebook (.ipynb) with Markdown commentary and executable Python code cells."""
            return await JupyterNotebookBuilder.build_and_save_notebook(
                db=db,
                project_id=project_id,
                title=title,
                sections=sections,
                filename=filename,
                execute_code=True,
            )

        async def generate_pareto_chart(
            file_id: str,
            sku_col: str = "sku",
            dollar_col: str = "dollar_volume",
            unit_col: Optional[str] = "unit_volume",
        ) -> Dict[str, Any]:
            """Generate a Pareto velocity concentration curve (accepts UUID or filename)."""
            file_rec = await FileIngestionService.resolve_project_file(db, project_id, file_id)
            if not file_rec:
                return {"error": f"File '{file_id}' not found."}
            df = pd.read_csv(file_rec.cleaned_path or file_rec.raw_path)
            return await ChartGenerationTool.create_pareto_chart(
                db=db,
                project_id=project_id,
                df_skus=df,
                sku_col=sku_col,
                dollar_col=dollar_col,
                unit_col=unit_col,
            )

        async def request_critic_review() -> Dict[str, Any]:
            """Invoke the dual-perspective Critic Agent to audit technical data science and executive business sanity."""
            critic = CriticAgent()
            return await critic.evaluate_project(db=db, project_id=project_id)

        async def generate_executive_deliverables() -> Dict[str, Any]:
            """Generate final Executive Strategy Memo, Full Technical Report, and reproducible Jupyter Notebook."""
            return await ReportingService.generate_executive_deliverables(db=db, project_id=project_id)

        async def log_assumption(
            assumption: str,
            rationale: Optional[str] = None,
            sensitivity_tier: str = "MODERATELY_SENSITIVE",
        ) -> Dict[str, Any]:
            """Record an explicit, auditable analytical assumption in project memory."""
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
            """Record an explicit, auditable methodological or business decision in project memory."""
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
                description="Run deterministic statistical and structural data profiling on a tabular dataset.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "rules": {"type": "array"},
                    },
                    "required": ["file_id"],
                    "additionalProperties": False,
                },
                handler=profile_dataset,
            ),
            ToolDefinition(
                name="clean_dataset",
                description="Clean tabular dataset while preserving raw values, capping fulfillment anomalies, and logging data quality issues.",
                parameters={
                    "type": "object",
                    "properties": {"file_id": {"type": "string"}},
                    "required": ["file_id"],
                    "additionalProperties": False,
                },
                handler=clean_dataset,
            ),
            ToolDefinition(
                name="run_python_analysis",
                description="Write and execute any custom Python script in the sandboxed runtime.",
                parameters={
                    "type": "object",
                    "properties": {
                        "code_string": {"type": "string"},
                        "script_name": {"type": "string"},
                    },
                    "required": ["code_string"],
                    "additionalProperties": False,
                },
                handler=run_python_analysis,
            ),
            ToolDefinition(
                name="create_custom_jupyter_notebook",
                description="Compile an interactive, well-documented Jupyter Notebook (.ipynb) with Markdown commentary and executable Python code cells.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "commentary": {"type": "string"},
                                    "code": {"type": "string"},
                                },
                                "required": ["title"],
                            },
                        },
                        "filename": {"type": "string"},
                    },
                    "required": ["title", "sections"],
                    "additionalProperties": False,
                },
                handler=create_custom_jupyter_notebook,
            ),
            ToolDefinition(
                name="calculate_velocity_segmentation",
                description="Classify SKUs by velocity (ABC Dollar/Unit), demand variability (XYZ), and intermittency (Syntetos-Boylan ADI/CV2).",
                parameters={
                    "type": "object",
                    "properties": {
                        "demand_file_id": {"type": "string"},
                        "parts_file_id": {"type": "string"},
                        "demand_window_weeks": {"type": "integer"},
                    },
                    "required": ["demand_file_id"],
                    "additionalProperties": False,
                },
                handler=calculate_velocity_segmentation,
            ),
            ToolDefinition(
                name="calculate_stocking_policy",
                description="Compute dynamic Safety Stock, ROP, Order-Up-To level, and Target WOS across all SKU-DC nodes.",
                parameters={
                    "type": "object",
                    "properties": {
                        "inventory_file_id": {"type": "string"},
                        "demand_file_id": {"type": "string"},
                        "parts_file_id": {"type": "string"},
                        "warehouses_file_id": {"type": "string"},
                    },
                    "required": ["inventory_file_id", "demand_file_id"],
                    "additionalProperties": False,
                },
                handler=calculate_stocking_policy,
            ),
            ToolDefinition(
                name="calculate_multi_echelon_policy",
                description="Compute Multi-Echelon MEIO inventory optimization (Hub-and-Spoke risk pooling and echelon buffer sizing).",
                parameters={
                    "type": "object",
                    "properties": {
                        "demand_file_id": {"type": "string"},
                        "central_dc_code": {"type": "string"},
                        "target_service_level": {"type": "number"},
                    },
                    "required": ["demand_file_id"],
                    "additionalProperties": False,
                },
                handler=calculate_multi_echelon_policy,
            ),
            ToolDefinition(
                name="generate_rebalance_candidates",
                description="Generate lateral inventory transfer action queue using exact Google OR-Tools MILP optimization.",
                parameters={
                    "type": "object",
                    "properties": {"transfer_lanes_file_id": {"type": "string"}},
                    "additionalProperties": False,
                },
                handler=generate_rebalance_candidates,
            ),
            ToolDefinition(
                name="generate_disposition_candidates",
                description="Generate disposition action queue (Vendor Returns for contract-eligible items, Liquidation, or Scrap).",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=generate_disposition_candidates,
            ),
            ToolDefinition(
                name="request_critic_review",
                description="Trigger formal Critic review audit to verify technical data science integrity and executive business sanity.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=request_critic_review,
            ),
            ToolDefinition(
                name="generate_executive_deliverables",
                description="Generate final Executive Strategy Memo, Full Technical Report, and reproducible Jupyter Notebook.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=generate_executive_deliverables,
            ),
            ToolDefinition(
                name="generate_pareto_chart",
                description="Generate a high-resolution Pareto concentration chart.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "sku_col": {"type": "string"},
                        "dollar_col": {"type": "string"},
                        "unit_col": {"type": "string"},
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
                        "assumption": {"type": "string"},
                        "rationale": {"type": "string"},
                        "sensitivity_tier": {"type": "string", "enum": ["ROBUST", "MODERATELY_SENSITIVE", "FRAGILE"]},
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
                        "decision": {"type": "string"},
                        "reason": {"type": "string"},
                        "alternatives": {"type": "array", "items": {"type": "string"}},
                        "risk_assessment": {"type": "string"},
                    },
                    "required": ["decision", "reason"],
                    "additionalProperties": False,
                },
                handler=log_decision,
            ),
            ToolDefinition(
                name="update_project_framing",
                description="Update structured framing, target decision, stakeholders, and constraints.",
                parameters={
                    "type": "object",
                    "properties": {
                        "objective": {"type": "string"},
                        "target_decision": {"type": "string"},
                        "stakeholders": {"type": "array", "items": {"type": "string"}},
                        "constraints": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                handler=update_project_framing,
            ),
            ToolDefinition(
                name="advance_project_phase",
                description="Advance project state machine to next phase.",
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
                        }
                    },
                    "required": ["target_phase"],
                    "additionalProperties": False,
                },
                handler=advance_project_phase,
            ),
            ToolDefinition(
                name="search_knowledge_base",
                description="Search the global knowledge base.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=search_knowledge_base,
            ),
        ]
