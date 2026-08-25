import pytest
from pathlib import Path
from sqlalchemy import select
from app.db.models import Artifact, Project, ProjectFile
from app.tools.file_tools import FileIngestionService
from app.tools.supply_chain import SupplyChainAnalyticsService


@pytest.mark.asyncio
async def test_velocity_segmentation(db_session):
    project = Project(title="SC Velocity Test", current_phase="DATA_PROFILED", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # Ingest synthetic demand dataset
    csv_demand = (
        b"week_date,part_number,warehouse_id,qty_demanded\n"
        b"2026-01-05,SKU_FAST_01,RNO,100\n"
        b"2026-01-12,SKU_FAST_01,RNO,95\n"
        b"2026-01-19,SKU_FAST_01,RNO,110\n"
        b"2026-01-26,SKU_FAST_01,RNO,105\n"
        b"2026-01-05,SKU_SLOW_02,CHI,2\n"
        b"2026-01-12,SKU_SLOW_02,CHI,0\n"
        b"2026-01-19,SKU_SLOW_02,CHI,0\n"
        b"2026-01-26,SKU_SLOW_02,CHI,3\n"
        b"2026-01-05,SKU_DEAD_03,ATL,0\n"
        b"2026-01-12,SKU_DEAD_03,ATL,0\n"
    )
    dem_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="weekly_demand.csv",
        content_bytes=csv_demand,
    )

    csv_parts = (
        b"part_number,unit_cost,lead_time_days,lifecycle_status,return_eligible\n"
        b"SKU_FAST_01,150.0,21,ACTIVE,True\n"
        b"SKU_SLOW_02,25.0,28,ACTIVE,True\n"
        b"SKU_DEAD_03,500.0,35,PHASE_OUT,False\n"
    )
    parts_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="parts.csv",
        content_bytes=csv_parts,
    )

    seg_res = await SupplyChainAnalyticsService.calculate_velocity_segmentation(
        db=db_session,
        project_id=project.id,
        demand_file_id=dem_rec.id,
        parts_file_id=parts_rec.id,
    )

    assert seg_res["total_skus"] >= 2
    assert seg_res["total_dollar_demand"] > 0
    assert "abc_dollar_distribution" in seg_res
    assert "demand_pattern_distribution" in seg_res
    assert Path(seg_res["artifact_path"]).exists()

    # Verify Artifact persisted
    stmt = select(Artifact).where(Artifact.project_id == project.id, Artifact.artifact_type == "ANALYSIS_TABLE")
    art = (await db_session.execute(stmt)).scalar_one_or_none()
    assert art is not None


@pytest.mark.asyncio
async def test_stocking_policy_rebalance_and_disposition(db_session):
    project = Project(title="SC Policy & Rebalance Test", current_phase="DATA_PROFILED", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # 1. Ingest Inventory Snapshot (RNO is long on SKU_01, CHI is short)
    csv_inv = (
        b"week_date,part_number,warehouse_id,on_hand_units,on_order_units\n"
        b"2026-06-29,SKU_01,RNO,500,0\n"    # Excess at RNO
        b"2026-06-29,SKU_01,CHI,5,0\n"      # Shortage at CHI
        b"2026-06-29,SKU_OBS_02,EWR,80,0\n" # Obsolete dead stock at EWR
    )
    inv_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="inventory_weekly.csv",
        content_bytes=csv_inv,
    )

    # 2. Ingest Demand
    csv_dem = (
        b"week_date,part_number,warehouse_id,qty_demanded\n"
        b"2026-06-01,SKU_01,RNO,20\n"
        b"2026-06-08,SKU_01,RNO,25\n"
        b"2026-06-01,SKU_01,CHI,30\n"
        b"2026-06-08,SKU_01,CHI,35\n"
        b"2026-06-01,SKU_OBS_02,EWR,0\n"
        b"2026-06-08,SKU_OBS_02,EWR,0\n"
    )
    dem_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="weekly_demand.csv",
        content_bytes=csv_dem,
    )

    # 3. Ingest Parts
    csv_parts = (
        b"part_number,unit_cost,lead_time_days,lifecycle_status,return_eligible\n"
        b"SKU_01,50.0,28,ACTIVE,True\n"
        b"SKU_OBS_02,100.0,35,OBSOLETE,False\n"
    )
    parts_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="parts.csv",
        content_bytes=csv_parts,
    )

    # 4. Ingest Transfer Lanes
    csv_lanes = (
        b"origin_dc,destination_dc,cost_per_unit,transit_days\n"
        b"RNO,CHI,4.50,3.0\n"
    )
    lanes_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="transfer_lanes.csv",
        content_bytes=csv_lanes,
    )

    # Execute Stocking Policy
    pol_res = await SupplyChainAnalyticsService.calculate_stocking_policy(
        db=db_session,
        project_id=project.id,
        inventory_file_id=inv_rec.id,
        demand_file_id=dem_rec.id,
        parts_file_id=parts_rec.id,
    )

    assert pol_res["total_nodes_evaluated"] == 3
    assert pol_res["overstocked_nodes_count"] >= 1
    assert pol_res["understocked_nodes_count"] >= 1

    # Execute Lateral Rebalance
    reb_res = await SupplyChainAnalyticsService.generate_rebalance_candidates(
        db=db_session,
        project_id=project.id,
        transfer_lanes_file_id=lanes_rec.id,
    )

    assert reb_res["total_rebalance_actions"] >= 1
    transfer = reb_res["top_transfers"][0]
    assert transfer["origin_dc"] == "RNO"
    assert transfer["destination_dc"] == "CHI"
    assert transfer["transfer_units"] > 0
    assert transfer["transit_days"] < transfer["supplier_lead_time_days"]

    # Execute Disposition
    disp_res = await SupplyChainAnalyticsService.generate_disposition_candidates(
        db=db_session,
        project_id=project.id,
    )

    assert disp_res["total_disposition_candidates"] >= 1
    assert disp_res["liquidation_scrap_count"] >= 1
