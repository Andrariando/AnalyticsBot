import json
import pytest
from pathlib import Path
from sqlalchemy import select
from app.db.models import Artifact, Project
from app.tools.notebook_tools import JupyterNotebookBuilder


@pytest.mark.asyncio
async def test_jupyter_notebook_builder(db_session):
    project = Project(title="Dynamic Python Notebook Test", current_phase="ANALYSIS_COMPLETE", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    sections = [
        {
            "title": "Data Ingestion & Summary",
            "commentary": "Load synthetic weekly sales and compute descriptive statistics.",
            "code": (
                "import pandas as pd\n"
                "import numpy as np\n"
                "df = pd.DataFrame({'week': range(1, 11), 'sales': [100, 120, 110, 140, 160, 150, 180, 200, 210, 230]})\n"
                "print(f'Average Sales: {df[\"sales\"].mean()}')"
            ),
        },
        {
            "title": "Trend Modeling",
            "commentary": "Fit a linear regression model to calculate weekly growth rate.",
            "code": (
                "slope, intercept = np.polyfit(df['week'], df['sales'], 1)\n"
                "print(f'Weekly Growth Slope: {slope:.2f}')"
            ),
        },
    ]

    res = await JupyterNotebookBuilder.build_and_save_notebook(
        db=db_session,
        project_id=project.id,
        title="Custom Demand Growth Analysis",
        sections=sections,
        filename="custom_demand_growth.ipynb",
        execute_code=True,
    )

    assert Path(res["notebook_path"]).exists()
    assert res["total_sections"] == 2
    assert res["execution_success"] is True

    # Validate valid JSON and nbformat
    with open(res["notebook_path"], "r", encoding="utf-8") as f:
        nb_data = json.load(f)
    assert nb_data["nbformat"] == 4
    assert len(nb_data["cells"]) >= 5  # Title + 2x (Markdown + Code)

    # Verify database artifact registration
    stmt = select(Artifact).where(Artifact.project_id == project.id, Artifact.artifact_type == "NOTEBOOK")
    art = (await db_session.execute(stmt)).scalar_one_or_none()
    assert art is not None
