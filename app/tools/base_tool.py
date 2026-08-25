import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    artifact_paths: list[str] = Field(default_factory=list)


class BaseTool(ABC):
    """Abstract base class for all analytical and system tools."""

    name: str = "base_tool"
    description: str = "Base tool description"

    async def execute(self, **kwargs: Any) -> ToolResult:
        start_time = time.perf_counter()
        try:
            res_data = await self._run(**kwargs)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                success=True,
                data=res_data.get("data"),
                artifact_paths=res_data.get("artifacts", []),
                execution_time_ms=round(duration_ms, 2),
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                success=False,
                error=str(e),
                execution_time_ms=round(duration_ms, 2),
            )

    @abstractmethod
    async def _run(self, **kwargs: Any) -> Dict[str, Any]:
        """Internal execution logic."""
        raise NotImplementedError
