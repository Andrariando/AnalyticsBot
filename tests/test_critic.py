import pytest
from sqlalchemy import select
from app.db.models import CriticReview, DataQualityIssue, Project, ProjectAssumption, ProjectDecision
from app.agents.critic import CriticAgent


@pytest.mark.asyncio
async def test_critic_review_with_valid_evidence(db_session):
    project = Project(title="Critic Audit Test", current_phase="ANALYSIS_COMPLETE", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # Add required assumptions & decisions
    ass = ProjectAssumption(
        project_id=project.id,
        assumption="Lead time standard deviation equals 3.5 days based on 26-week supplier log.",
        sensitivity_tier="MODERATELY_SENSITIVE",
        status="ACTIVE",
    )
    dec = ProjectDecision(
        project_id=project.id,
        decision="Use 95% target service level for Class A EV parts.",
        reason="Prevents costly assembly line stoppages.",
        status="APPROVED",
    )
    db_session.add_all([ass, dec])
    await db_session.commit()

    critic = CriticAgent()
    res = await critic.evaluate_project(db=db_session, project_id=project.id)

    assert "decision" in res
    assert "technical_findings" in res
    assert "business_findings" in res
    assert res["confidence_score"] > 0.0

    # Verify critic review persisted in DB
    stmt = select(CriticReview).where(CriticReview.project_id == project.id)
    rev_rec = (await db_session.execute(stmt)).scalar_one_or_none()
    assert rev_rec is not None


@pytest.mark.asyncio
async def test_critic_flags_critical_issues(db_session):
    project = Project(title="Critic Blocking Test", current_phase="ANALYSIS_COMPLETE", status="ACTIVE")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # Add a blocking CRITICAL data quality issue
    dqi = DataQualityIssue(
        project_id=project.id,
        file_id=None,
        check_name="CORRUPT_DEMAND_SERIES",
        severity="CRITICAL",
        details={"anomaly": "Fulfillment exceeds demand by > 500% in 15 rows."},
        treatment_applied=None,
    )
    db_session.add(dqi)
    await db_session.commit()

    critic = CriticAgent()
    res = await critic.evaluate_project(db=db_session, project_id=project.id)

    assert res["decision"] == "REVISE_REQUIRED"
    assert len(res["critical_issues"]) >= 1
    assert any("critical data quality issues" in issue.lower() for issue in res["critical_issues"])
