import pytest
from pathlib import Path
from sqlalchemy import select
from app.db.models import Artifact, Project, Recommendation
from app.tools.file_tools import FileIngestionService
from app.tools.reporting import ReportingService


@pytest.mark.asyncio
async def test_generate_executive_deliverables(db_session):
    project = Project(title="EV Supply Chain Optimization", current_phase="VALIDATED", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # Initialize project directories and mock analysis csv
    project_dir = FileIngestionService.initialize_project_workspace(project.id)
    analysis_dir = project_dir / "analysis"
    outputs_dir = project_dir / "outputs"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Write dummy stocking policy evaluation csv
    policy_csv = analysis_dir / "stocking_policy_evaluation.csv"
    with open(policy_csv, "w", encoding="utf-8") as f:
        f.write(
            "sku,dc,unit_cost,on_hand_dollars,excess_dollars,shortage_dollars\n"
            "SKU_01,RNO,50.0,25000.0,15000.0,0.0\n"
            "SKU_01,CHI,50.0,250.0,0.0,8000.0\n"
        )

    # Write dummy rebalance action queue csv
    reb_csv = outputs_dir / "rebalance_action_queue.csv"
    with open(reb_csv, "w", encoding="utf-8") as f:
        f.write(
            "sku,origin_dc,destination_dc,transfer_units,rebalanced_asset_value,estimated_freight_cost\n"
            "SKU_01,RNO,CHI,150,7500.0,675.0\n"
        )

    res = await ReportingService.generate_executive_deliverables(
        db=db_session,
        project_id=project.id,
    )

    assert Path(res["executive_memo_path"]).exists()
    assert Path(res["technical_report_path"]).exists()
    assert Path(res["notebook_path"]).exists()
    assert res["total_on_hand_working_capital"] == 25250.0
    assert res["total_excess_capital"] == 15000.0
    assert res["total_rebalanced_value"] == 7500.0

    # Verify artifacts recorded in database
    stmt = select(Artifact).where(Artifact.project_id == project.id)
    artifacts = (await db_session.execute(stmt)).scalars().all()
    assert len(artifacts) >= 3

    # Verify recommendations recorded in database
    rec_stmt = select(Recommendation).where(Recommendation.project_id == project.id)
    recs = (await db_session.execute(rec_stmt)).scalars().all()
    assert len(recs) >= 2

    # Verify project status completed
    await db_session.refresh(project)
    assert project.current_phase == "COMPLETE"
    assert project.status == "COMPLETED"
