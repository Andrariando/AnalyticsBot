import os
import pytest
from pathlib import Path
import pandas as pd
from sqlalchemy import select
from app.db.models import Artifact, DataQualityIssue, Project, ProjectFile
from app.tools.file_tools import FileIngestionService
from app.tools.runtime import PythonAnalyticsRuntime
from app.tools.cleaning_tools import DataCleaningService
from app.tools.visualization_tools import ChartGenerationTool


@pytest.mark.asyncio
async def test_sandboxed_python_execution():
    project_id = "proj_test_runtime"
    script = """
import os
import pandas as pd
import numpy as np

# Read environment variables
outputs_dir = os.environ.get("OUTPUTS_DIR", ".")
data = {"sku": ["A", "B", "C"], "demand": [10, 20, 30]}
df = pd.DataFrame(data)

summary = {"total_demand": int(df["demand"].sum()), "mean_demand": float(df["demand"].mean())}
output_file = os.path.join(outputs_dir, "test_summary.json")

import json
with open(output_file, "w") as f:
    json.dump(summary, f)

print(f"CALCULATION_COMPLETE: total={summary['total_demand']}")
"""

    res = await PythonAnalyticsRuntime.execute_code(
        project_id=project_id,
        code_string=script,
        script_name="calc_test.py",
    )

    assert res.success is True
    assert res.return_code == 0
    assert "CALCULATION_COMPLETE: total=60" in res.stdout
    assert len(res.created_artifacts) == 1
    assert "test_summary.json" in res.created_artifacts[0]


@pytest.mark.asyncio
async def test_sandboxed_python_timeout():
    project_id = "proj_test_timeout"
    infinite_loop_script = """
import time
while True:
    time.sleep(0.1)
"""

    res = await PythonAnalyticsRuntime.execute_code(
        project_id=project_id,
        code_string=infinite_loop_script,
        script_name="loop_test.py",
        timeout_seconds=2.0,
    )

    assert res.success is False
    assert res.return_code == -1
    assert "timed out" in res.stderr.lower()


@pytest.mark.asyncio
async def test_data_cleaning_service(db_session):
    project_id = "proj_test_cleaning"
    # Create project
    project = Project(title="Cleaning Test", current_phase="DATA_PROFILED", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # Ingest dirty dataset (fulfillment > demand, negative stock, duplicate row)
    csv_bytes = (
        b"sku,dc,qty_demanded,qty_fulfilled,stock_qty\n"
        b"SKU_01,RNO,100,120,50\n"  # Fulfillment > Demand
        b"SKU_02,CHI,200,200,-10\n"  # Negative stock
        b"SKU_03,ATL,50,50,30\n"
        b"SKU_03,ATL,50,50,30\n"     # Duplicate row
    )

    file_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="dirty_data.csv",
        content_bytes=csv_bytes,
    )

    clean_res = await DataCleaningService.clean_tabular_dataset(
        db=db_session,
        project_id=project.id,
        file_id=file_rec.id,
    )

    assert clean_res["raw_rows"] == 4
    assert clean_res["cleaned_rows"] == 3  # Duplicate dropped
    assert clean_res["issues_logged"] >= 2

    # Check that cleaned file exists
    cleaned_path = Path(clean_res["cleaned_path"])
    assert cleaned_path.exists()
    df_clean = pd.read_csv(cleaned_path)

    # Verify raw values preserved and clean values corrected
    assert "qty_fulfilled_raw" in df_clean.columns
    assert "qty_fulfilled_clean" in df_clean.columns
    assert "stock_qty_raw" in df_clean.columns
    assert "stock_qty_clean" in df_clean.columns

    # Capped fulfillment check: for SKU_01, fulfilled_clean == 100 (capped at demanded)
    sku01 = df_clean[df_clean["sku"] == "SKU_01"].iloc[0]
    assert sku01["qty_fulfilled_raw"] == 120
    assert sku01["qty_fulfilled_clean"] == 100

    # Negative stock check: for SKU_02, stock_qty_clean == 0
    sku02 = df_clean[df_clean["sku"] == "SKU_02"].iloc[0]
    assert sku02["stock_qty_raw"] == -10
    assert sku02["stock_qty_clean"] == 0

    # Verify database issues recorded
    stmt = select(DataQualityIssue).where(DataQualityIssue.project_id == project.id)
    db_issues = (await db_session.execute(stmt)).scalars().all()
    assert len(db_issues) >= 2


@pytest.mark.asyncio
async def test_decision_chart_generation(db_session):
    project_id = "proj_test_charts"
    project = Project(title="Chart Test", current_phase="ANALYSIS_COMPLETE", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # 1. Pareto Chart
    df_pareto = pd.DataFrame({
        "sku": [f"SKU_{i:02d}" for i in range(1, 21)],
        "dollar_volume": [100000 / (i**1.2) for i in range(1, 21)],
        "unit_volume": [5000 / (i**0.8) for i in range(1, 21)],
    })
    pareto_res = await ChartGenerationTool.create_pareto_chart(
        db=db_session,
        project_id=project.id,
        df_skus=df_pareto,
        dollar_col="dollar_volume",
        unit_col="unit_volume",
    )
    assert Path(pareto_res["file_path"]).exists()
    assert os.path.getsize(pareto_res["file_path"]) > 10000

    # 2. Inventory Coverage Chart
    df_coverage = pd.DataFrame({
        "sku": [f"SKU_{i:02d}" for i in range(1, 11)],
        "current_wos": [2, 5, 12, 35, 1, 8, 45, 14, 3, 20],
        "target_wos": [6, 6, 8, 12, 6, 8, 12, 8, 6, 10],
    })
    cov_res = await ChartGenerationTool.create_inventory_vs_target_chart(
        db=db_session,
        project_id=project.id,
        df_inventory=df_coverage,
    )
    assert Path(cov_res["file_path"]).exists()

    # 3. Capacity Chart
    df_warehouses = pd.DataFrame({
        "dc_code": ["RNO", "DEN", "CHI", "ATL", "EWR"],
        "occupied_pallets": [115, 60, 120, 90, 80],
        "dedicated_pallet_capacity": [118, 95, 175, 155, 145],
    })
    cap_res = await ChartGenerationTool.create_capacity_utilization_chart(
        db=db_session,
        project_id=project.id,
        df_warehouses=df_warehouses,
    )
    assert Path(cap_res["file_path"]).exists()

    # Verify Artifacts table records
    stmt = select(Artifact).where(Artifact.project_id == project.id)
    artifacts = (await db_session.execute(stmt)).scalars().all()
    assert len(artifacts) == 3
