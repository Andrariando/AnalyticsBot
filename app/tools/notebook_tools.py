import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Artifact
from app.tools.file_tools import FileIngestionService
from app.tools.runtime import PythonAnalyticsRuntime, PythonExecutionResult

logger = logging.getLogger(__name__)


class JupyterNotebookBuilder:
    """
    Service that allows autonomous agents to write, execute, and compile custom Python code
    into interactive, fully documented Jupyter Notebooks (.ipynb).
    """

    @classmethod
    def create_notebook_structure(
        cls,
        title: str,
        sections: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Builds a valid Jupyter Notebook v4 JSON structure from a list of sections.
        Each section contains:
        - 'title': Section title (Markdown)
        - 'commentary': Analytical explanation, hypothesis, or interpretation (Markdown)
        - 'code': Python code string (Code cell)
        """
        cells = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"# 📓 {title}\n",
                    f"*Generated autonomously by Business Analytics Operating System*\n\n",
                    f"---\n",
                ],
            }
        ]

        exec_count = 1
        for idx, sec in enumerate(sections, start=1):
            sec_title = sec.get("title", f"Section {idx}")
            commentary = sec.get("commentary", "")
            code = sec.get("code", "")

            # Add Markdown explanation cell
            md_lines = [f"## {idx}. {sec_title}\n\n"]
            if commentary:
                md_lines.append(f"{commentary}\n")

            cells.append({
                "cell_type": "markdown",
                "metadata": {},
                "source": md_lines,
            })

            # Add Python code cell
            if code:
                code_lines = [line + "\n" for line in code.strip().split("\n")]
                cells.append({
                    "cell_type": "code",
                    "execution_count": exec_count,
                    "metadata": {},
                    "outputs": [],
                    "source": code_lines,
                })
                exec_count += 1

        notebook_json = {
            "cells": cells,
            "metadata": {
                "language_info": {
                    "name": "python",
                    "version": "3.13.0",
                    "mimetype": "text/x-python",
                    "file_extension": ".py",
                },
                "kernelspec": {
                    "name": "python3",
                    "display_name": "Python 3",
                    "language": "python",
                },
                "orig_nbformat": 4,
            },
            "nbformat": 4,
            "nbformat_minor": 4,
        }
        return notebook_json

    @classmethod
    async def build_and_save_notebook(
        cls,
        db: AsyncSession,
        project_id: str,
        title: str,
        sections: List[Dict[str, Any]],
        filename: str = "custom_analysis.ipynb",
        execute_code: bool = True,
    ) -> Dict[str, Any]:
        """
        Builds, saves, registers, and optionally executes the custom Python notebook.
        """
        project_dir = FileIngestionService.get_project_dir(project_id)
        outputs_dir = project_dir / "outputs"
        working_dir = project_dir / "working"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        working_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".ipynb"):
            filename += ".ipynb"

        nb_path = outputs_dir / filename
        nb_json = cls.create_notebook_structure(title=title, sections=sections)

        with open(nb_path, "w", encoding="utf-8") as f:
            json.dump(nb_json, f, indent=2)

        # Register artifact in database
        art = Artifact(
            project_id=project_id,
            artifact_type="NOTEBOOK",
            file_path=str(nb_path),
            summary=f"Custom Jupyter Notebook: {title} with {len(sections)} analytical code sections.",
        )
        db.add(art)
        await db.commit()

        # If requested, concatenate all code and execute in sandboxed runtime to verify it works
        exec_result: Optional[PythonExecutionResult] = None
        if execute_code:
            combined_code = "\n\n".join([sec.get("code", "") for sec in sections if sec.get("code")])
            if combined_code.strip():
                exec_result = await PythonAnalyticsRuntime.execute_code(
                    project_id=project_id,
                    code_string=combined_code,
                    script_name=filename.replace(".ipynb", "_runner.py"),
                )

        return {
            "project_id": project_id,
            "notebook_title": title,
            "notebook_path": str(nb_path),
            "total_sections": len(sections),
            "execution_success": exec_result.success if exec_result else True,
            "created_artifacts": exec_result.created_artifacts if exec_result else [],
            "execution_error": exec_result.error_message if exec_result and not exec_result.success else None,
        }
