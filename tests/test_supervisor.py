import pytest
from pathlib import Path
from sqlalchemy import select
from app.agents.base_agent import BaseAgent, ToolDefinition
from app.agents.supervisor import SupervisorAgent
from app.db.models import Project, ProjectAssumption, ProjectDecision, ProjectFile
from app.tools.file_tools import FileIngestionService
from app.core.state_machine import ProjectPhase


@pytest.mark.asyncio
async def test_supervisor_tool_execution(db_session):
    # 1. Create a project
    project = Project(
        title="Inventory Optimization Test",
        objective="Analyze stockouts vs dead stock",
        current_phase="INITIALIZED",
        status="ACTIVE",
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # 2. Ingest a sample dataset
    csv_bytes = b"part_number,warehouse,demand_qty,stock_qty\nSKU_01,RNO,120,40\nSKU_02,CHI,300,500\nSKU_03,ATL,0,150\n"
    file_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="inventory_snapshot.csv",
        content_bytes=csv_bytes,
    )

    # 3. Instantiate Supervisor and inspect built tools
    supervisor = SupervisorAgent()
    tools = supervisor._build_supervisor_tools(db=db_session, project_id=project.id)
    tool_map = {t.name: t for t in tools}

    assert "inspect_project_files" in tool_map
    assert "profile_dataset" in tool_map
    assert "log_assumption" in tool_map
    assert "log_decision" in tool_map
    assert "advance_project_phase" in tool_map

    # Execute inspect_project_files
    inspect_res = await tool_map["inspect_project_files"].handler()
    assert inspect_res["file_count"] == 1
    assert inspect_res["files"][0]["filename"] == "inventory_snapshot.csv"

    # Execute profile_dataset
    profile_res = await tool_map["profile_dataset"].handler(file_id=file_rec.id)
    assert profile_res["row_count"] == 3
    assert profile_res["column_count"] == 4

    # Execute log_assumption
    ass_res = await tool_map["log_assumption"].handler(
        assumption="Assume 26-week demand window balances recency and seasonal signal",
        rationale="Prevents COVID-era distortion while providing enough sample size",
        sensitivity_tier="MODERATELY_SENSITIVE",
    )
    assert ass_res["status"] == "logged"

    # Verify assumption saved in DB
    stmt = select(ProjectAssumption).where(ProjectAssumption.project_id == project.id)
    res = await db_session.execute(stmt)
    assumptions = res.scalars().all()
    assert len(assumptions) == 1
    assert "26-week demand" in assumptions[0].assumption

    # Execute log_decision
    dec_res = await tool_map["log_decision"].handler(
        decision="Implement dynamic Weeks of Supply targets by ABC/XYZ velocity tier",
        reason="Static min/max is causing concurrent stockouts and pallet bloat",
        alternatives=["Keep static min/max", "Implement single global safety stock"],
        risk_assessment="Requires planner buy-in for non-linear safety stock logic",
    )
    assert dec_res["status"] == "logged"

    # Verify decision saved in DB
    stmt = select(ProjectDecision).where(ProjectDecision.project_id == project.id)
    res = await db_session.execute(stmt)
    decisions = res.scalars().all()
    assert len(decisions) == 1
    assert "Weeks of Supply" in decisions[0].decision

    # Execute advance_project_phase
    phase_res = await tool_map["advance_project_phase"].handler(target_phase="PROBLEM_FRAMED")
    assert phase_res["status"] == "transitioned"
    assert phase_res["current_phase"] == "PROBLEM_FRAMED"


@pytest.mark.asyncio
async def test_supervisor_live_turn(db_session):
    """Live turn test with OpenAI if API key is configured."""
    from app.config import settings
    if not settings.OPENAI_API_KEY:
        pytest.skip("OPENAI_API_KEY not configured, skipping live LLM test.")

    project = Project(
        title="Live Problem Framing Test",
        objective="Identify core inventory decisions",
        current_phase="INITIALIZED",
        status="ACTIVE",
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # Ingest a small dataset
    csv_bytes = b"part_number,warehouse,demand_qty,stock_qty\nSKU_A,RNO,100,20\nSKU_B,CHI,10,200\n"
    await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project.id,
        filename="quick_test.csv",
        content_bytes=csv_bytes,
    )

    supervisor = SupervisorAgent()
    response = await supervisor.execute_turn(
        db=db_session,
        project_id=project.id,
        user_message="Inspect the uploaded dataset and advance the project to PROBLEM_FRAMED phase.",
    )

    assert len(response.content) > 20
    assert response.iteration_count >= 1
    # Check that tools were called by the LLM
    called_tool_names = [tc.tool_name for tc in response.tool_calls]
    assert len(called_tool_names) > 0
