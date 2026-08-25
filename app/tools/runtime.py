import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.tools.file_tools import FileIngestionService


class PythonExecutionResult(BaseModel):
    success: bool
    return_code: int
    stdout: str
    stderr: str
    execution_time_ms: float
    created_artifacts: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class PythonAnalyticsRuntime:
    """
    Sandboxed execution environment for running Python analytics, modeling,
    and transformations inside an isolated project workspace.
    """

    DEFAULT_TIMEOUT_SECONDS = 45.0

    @classmethod
    async def execute_code(
        cls,
        project_id: str,
        code_string: str,
        script_name: str = "analysis_script.py",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> PythonExecutionResult:
        """
        Saves a Python script into projects/{project_id}/working/ and executes it in a separate process.
        """
        start_time_epoch = time.time()
        start_time_perf = time.perf_counter()
        project_dir = FileIngestionService.initialize_project_workspace(project_id)
        working_dir = project_dir / "working"
        script_path = working_dir / script_name

        subdirs_to_watch = [project_dir / "analysis", project_dir / "charts", project_dir / "outputs"]
        for d in subdirs_to_watch:
            d.mkdir(parents=True, exist_ok=True)

        # Snapshot modification times
        initial_mtimes = {
            p: p.stat().st_mtime
            for d in subdirs_to_watch
            for p in d.glob("**/*")
            if p.is_file()
        }

        # Write script to working directory
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code_string)

        # Set execution environment variables
        env = os.environ.copy()
        env["PROJECT_ID"] = project_id
        env["WORKSPACE_DIR"] = str(project_dir)
        env["RAW_DIR"] = str(project_dir / "raw")
        env["CLEANED_DIR"] = str(project_dir / "cleaned")
        env["ANALYSIS_DIR"] = str(project_dir / "analysis")
        env["CHARTS_DIR"] = str(project_dir / "charts")
        env["OUTPUTS_DIR"] = str(project_dir / "outputs")
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script_path),
                cwd=str(working_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds
                )
                return_code = process.returncode or 0
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration_ms = (time.perf_counter() - start_time_perf) * 1000.0
                return PythonExecutionResult(
                    success=False,
                    return_code=-1,
                    stdout="",
                    stderr=f"Execution timed out after {timeout_seconds} seconds.",
                    execution_time_ms=round(duration_ms, 2),
                    error_message=f"Timeout limit ({timeout_seconds}s) exceeded.",
                )

            duration_ms = (time.perf_counter() - start_time_perf) * 1000.0

            # Detect newly created or updated files
            newly_created = []
            for d in subdirs_to_watch:
                for p in d.glob("**/*"):
                    if p.is_file():
                        mtime = p.stat().st_mtime
                        if p not in initial_mtimes or mtime > initial_mtimes[p] or mtime >= start_time_epoch - 1.0:
                            newly_created.append(str(p))

            return PythonExecutionResult(
                success=(return_code == 0),
                return_code=return_code,
                stdout=stdout,
                stderr=stderr,
                execution_time_ms=round(duration_ms, 2),
                created_artifacts=newly_created,
                error_message=stderr if return_code != 0 else None,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time_perf) * 1000.0
            return PythonExecutionResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=str(e),
                execution_time_ms=round(duration_ms, 2),
                error_message=f"Failed to launch Python subprocess: {str(e)}",
            )
