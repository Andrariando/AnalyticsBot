import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.base_agent import BaseAgent, ToolDefinition, AgentResponse
from app.agents.prompts.data_scientist import DATA_SCIENTIST_SYSTEM_PROMPT
from app.config import settings
from app.tools.supply_chain import SupplyChainAnalyticsService
from app.tools.modeling import PredictiveModelingService
from app.tools.runtime import PythonAnalyticsRuntime
from app.tools.notebook_tools import JupyterNotebookBuilder

logger = logging.getLogger(__name__)


class DataScientistAgent:
    """
    Senior Data Scientist & Operations Research Analyst responsible for data modeling,
    statistical calculations, velocity segmentation, inventory policy, forecasting,
    and custom Jupyter notebook creation.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.DATA_SCIENTIST_MODEL

    async def execute_task(
        self,
        db: AsyncSession,
        project_id: str,
        task_description: str,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """
        Executes a targeted data science, OR, or notebook generation task for a project.
        """
        tools = self._build_data_scientist_tools(db=db, project_id=project_id)
        agent = BaseAgent(
            system_prompt=DATA_SCIENTIST_SYSTEM_PROMPT,
            model_name=self.model_name,
            tools=tools,
            max_iterations=10,
        )

        messages = [
            {
                "role": "user",
                "content": f"Project ID: {project_id}\nTask: {task_description}\nContext: {context_data or {}}",
            }
        ]

        return await agent.run_turn(messages=messages)

    def _build_data_scientist_tools(self, db: AsyncSession, project_id: str) -> List[ToolDefinition]:
        """Construct the Data Scientist's specialized analytics, modeling, and notebook creation tool suite."""

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

        async def generate_rebalance_candidates(
            transfer_lanes_file_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Generate multi-DC lateral inventory transfer queue matching long nodes with short nodes."""
            return await SupplyChainAnalyticsService.generate_rebalance_candidates(
                db=db,
                project_id=project_id,
                transfer_lanes_file_id=transfer_lanes_file_id,
            )

        async def generate_disposition_candidates() -> Dict[str, Any]:
            """Generate excess inventory disposition queue (Vendor Returns, Liquidation, Scrap)."""
            return await SupplyChainAnalyticsService.generate_disposition_candidates(
                db=db,
                project_id=project_id,
            )

        async def train_demand_forecast(
            demand_file_id: str,
            target_sku: Optional[str] = None,
            forecast_horizon_weeks: int = 4,
        ) -> Dict[str, Any]:
            """Fit time-series forecasting model comparing against Naive and Moving Average baselines."""
            return await PredictiveModelingService.train_demand_forecast(
                db=db,
                project_id=project_id,
                demand_file_id=demand_file_id,
                target_sku=target_sku,
                forecast_horizon_weeks=forecast_horizon_weeks,
            )

        async def train_stockout_classifier(
            inventory_file_id: str,
            demand_file_id: str,
        ) -> Dict[str, Any]:
            """Train stockout risk classifier comparing against heuristic threshold baseline."""
            return await PredictiveModelingService.train_stockout_classifier(
                db=db,
                project_id=project_id,
                inventory_file_id=inventory_file_id,
                demand_file_id=demand_file_id,
            )

        async def run_custom_analysis(code_string: str, script_name: str = "custom_script.py") -> Dict[str, Any]:
            """Run custom Python analytics script in sandboxed project runtime."""
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
            """Compile an interactive, commented Jupyter Notebook (.ipynb) with explanatory Markdown and executable Python code cells."""
            return await JupyterNotebookBuilder.build_and_save_notebook(
                db=db,
                project_id=project_id,
                title=title,
                sections=sections,
                filename=filename,
                execute_code=True,
            )

        return [
            ToolDefinition(
                name="run_custom_analysis",
                description="Write and execute any arbitrary custom Python analysis script in the sandboxed runtime. Can perform custom data munging, regression, optimization, or custom chart plotting.",
                parameters={
                    "type": "object",
                    "properties": {
                        "code_string": {"type": "string", "description": "Python code to execute."},
                        "script_name": {"type": "string", "description": "Filename to save the script under."},
                    },
                    "required": ["code_string"],
                    "additionalProperties": False,
                },
                handler=run_custom_analysis,
            ),
            ToolDefinition(
                name="create_custom_jupyter_notebook",
                description="Compile an interactive, well-documented Jupyter Notebook (.ipynb) with Markdown commentary and executable Python code cells.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Title of the notebook."},
                        "sections": {
                            "type": "array",
                            "description": "List of sections. Each section has 'title', 'commentary' (Markdown text), and 'code' (Python code).",
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
                        "filename": {"type": "string", "description": "Filename e.g. 'demand_elasticity_analysis.ipynb'."},
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
                name="generate_rebalance_candidates",
                description="Generate lateral inventory transfer action queue matching long nodes with short nodes.",
                parameters={
                    "type": "object",
                    "properties": {
                        "transfer_lanes_file_id": {"type": "string"},
                    },
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
                name="train_demand_forecast",
                description="Train time-series forecasting model comparing against Naive, Moving Average, and Croston baselines.",
                parameters={
                    "type": "object",
                    "properties": {
                        "demand_file_id": {"type": "string"},
                        "target_sku": {"type": "string"},
                        "forecast_horizon_weeks": {"type": "integer"},
                    },
                    "required": ["demand_file_id"],
                    "additionalProperties": False,
                },
                handler=train_demand_forecast,
            ),
            ToolDefinition(
                name="train_stockout_classifier",
                description="Train machine learning classifier to predict stockout risk in next 4 weeks.",
                parameters={
                    "type": "object",
                    "properties": {
                        "inventory_file_id": {"type": "string"},
                        "demand_file_id": {"type": "string"},
                    },
                    "required": ["inventory_file_id", "demand_file_id"],
                    "additionalProperties": False,
                },
                handler=train_stockout_classifier,
            ),
        ]
