import asyncio
import pytest
from app.agents.task_runner import ParallelTaskRunner


@pytest.mark.asyncio
async def test_parallel_task_runner():
    async def sample_async_calc(val: int):
        await asyncio.sleep(0.05)
        return val * 2

    tasks = [
        {"name": "calc_1", "coroutine": sample_async_calc(10)},
        {"name": "calc_2", "coroutine": sample_async_calc(20)},
        {"name": "calc_3", "coroutine": sample_async_calc(30)},
    ]

    results = await ParallelTaskRunner.run_parallel_tasks(tasks)

    assert len(results) == 3
    assert results[0]["task_name"] == "calc_1"
    assert results[0]["result"] == 20
    assert results[1]["result"] == 40
    assert results[2]["result"] == 60
