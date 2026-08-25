import pytest
from sqlalchemy import select
from app.db.models import ModelRun, Project, ProjectFile
from app.tools.file_tools import FileIngestionService
from app.tools.modeling import PredictiveModelingService
from app.agents.data_scientist import DataScientistAgent


@pytest.mark.asyncio
async def test_forecasting_with_baselines(db_session):
    project = Project(title="Forecasting Test", current_phase="METHOD_SELECTED", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # 16 weeks of demand data for SKU_A
    lines = ["week_date,part_number,qty_demanded"]
    for w in range(1, 17):
        lines.append(f"2026-{w:02d}-01,SKU_A,{20 + (w % 4)*5}")
    csv_bytes = "\n".join(lines).encode("utf-8")

    dem_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="demand_ts.csv",
        content_bytes=csv_bytes,
    )

    res = await PredictiveModelingService.train_demand_forecast(
        db=db_session,
        project_id=project.id,
        demand_file_id=dem_rec.id,
        target_sku="SKU_A",
        forecast_horizon_weeks=4,
    )

    assert "baseline_naive" in res
    assert "baseline_moving_avg" in res
    assert "model_exponential_smoothing" in res
    assert res["baseline_naive"]["mae"] >= 0

    # Verify model run persisted in database
    stmt = select(ModelRun).where(ModelRun.project_id == project.id, ModelRun.problem_type == "FORECAST")
    run_rec = (await db_session.execute(stmt)).scalar_one_or_none()
    assert run_rec is not None
    assert run_rec.model_name == "Demand_Forecast_SKU_SKU_A"


@pytest.mark.asyncio
async def test_stockout_classification(db_session):
    project = Project(title="Classification Test", current_phase="METHOD_SELECTED", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # Create 30 synthetic inventory and demand rows
    inv_lines = ["part_number,warehouse_id,on_hand_units"]
    dem_lines = ["part_number,warehouse_id,qty_demanded"]
    for i in range(1, 31):
        sku = f"SKU_{i:02d}"
        inv_lines.append(f"{sku},RNO,{10 if i < 10 else 100}")
        dem_lines.append(f"{sku},RNO,{25 if i < 10 else 15}")

    inv_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="inv_class.csv",
        content_bytes="\n".join(inv_lines).encode("utf-8"),
    )
    dem_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="dem_class.csv",
        content_bytes="\n".join(dem_lines).encode("utf-8"),
    )

    res = await PredictiveModelingService.train_stockout_classifier(
        db=db_session,
        project_id=project.id,
        inventory_file_id=inv_rec.id,
        demand_file_id=dem_rec.id,
    )

    assert "baseline_heuristic_metrics" in res
    assert "random_forest_metrics" in res
    assert res["random_forest_metrics"]["f1_score"] >= 0

    # Verify model run in DB
    stmt = select(ModelRun).where(ModelRun.project_id == project.id, ModelRun.problem_type == "CLASSIFICATION")
    run_rec = (await db_session.execute(stmt)).scalar_one_or_none()
    assert run_rec is not None
