import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import get_db


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_create_and_get_project(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create Project
        create_res = await ac.post(
            "/api/projects",
            json={
                "title": "Northline Mobility Inventory Optimization",
                "objective": "Recommend stocking policy and lateral rebalances",
                "business_context": {"network_dcs": 5, "active_skus": 120},
            },
        )
        assert create_res.status_code == 201
        project_data = create_res.json()
        project_id = project_data["id"]
        assert project_data["title"] == "Northline Mobility Inventory Optimization"
        assert project_data["current_phase"] == "INITIALIZED"

        # Get Project by ID
        get_res = await ac.get(f"/api/projects/{project_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == project_id

        # Get Project State
        state_res = await ac.get(f"/api/projects/{project_id}/state")
        assert state_res.status_code == 200
        state_data = state_res.json()
        assert state_data["project_id"] == project_id
        assert state_data["current_phase"] == "INITIALIZED"

    app.dependency_overrides.clear()
