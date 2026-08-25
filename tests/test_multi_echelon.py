import pytest
from pathlib import Path
from app.db.models import Project, ProjectFile
from app.tools.file_tools import FileIngestionService
from app.tools.multi_echelon import MultiEchelonAnalyticsService


@pytest.mark.asyncio
async def test_multi_echelon_meio_calculation(db_session):
    project = Project(title="MEIO Hub-Spoke Test", current_phase="ANALYSIS_COMPLETE", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    project_dir = FileIngestionService.initialize_project_workspace(project.id)
    raw_dir = project_dir / "raw"

    # Create dummy multi-warehouse demand data
    demand_csv = raw_dir / "weekly_demand.csv"
    with open(demand_csv, "w", encoding="utf-8") as f:
        f.write(
            "week,sku,warehouse,qty\n"
            "1,PART_01,RDC_East,100\n"
            "2,PART_01,RDC_East,120\n"
            "1,PART_01,RDC_West,80\n"
            "2,PART_01,RDC_West,90\n"
            "1,PART_01,RDC_Central,50\n"
            "2,PART_01,RDC_Central,45\n"
        )

    file_rec = ProjectFile(
        project_id=project.id,
        filename="weekly_demand.csv",
        file_type="CSV",
        raw_path=str(demand_csv),
        cleaned_path=str(demand_csv),
    )
    db_session.add(file_rec)
    await db_session.commit()
    await db_session.refresh(file_rec)

    res = await MultiEchelonAnalyticsService.calculate_multi_echelon_policy(
        db=db_session,
        project_id=project.id,
        demand_file_id=file_rec.id,
        central_dc_code="CDC_MAIN",
        target_service_level=0.95,
    )

    assert "total_skus_evaluated" in res
    assert res["total_skus_evaluated"] == 1
    assert "total_ss_units_saved_by_pooling" in res
    assert res["total_ss_units_saved_by_pooling"] > 0
    assert Path(res["file_path"]).exists()
