import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ParallelTaskRunner:
    """
    Asynchronous executor for running multiple subagent analytical tasks concurrently.
    """

    @classmethod
    async def run_parallel_tasks(
        cls,
        tasks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Executes a list of async callables concurrently.
        Each task is a dict:
        - 'name': str
        - 'coroutine': Coroutine
        """
        names = [t.get("name", f"task_{i}") for i, t in enumerate(tasks)]
        coroutines = [t["coroutine"] for t in tasks]

        logger.info(f"Running {len(tasks)} subagent tasks in parallel: {names}")
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        output = []
        for name, res in zip(names, results):
            if isinstance(res, Exception):
                logger.error(f"Task {name} failed with error: {res}")
                output.append({"task_name": name, "success": False, "error": str(res)})
            else:
                output.append({"task_name": name, "success": True, "result": res})

        return output
