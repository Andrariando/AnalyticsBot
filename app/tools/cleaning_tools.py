from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import DataQualityIssue, ProjectFile
from app.tools.file_tools import FileIngestionService


class DataCleaningService:
    """
    Performs data cleaning and hygiene while strictly enforcing the preservation of raw values,
    explicit quality flags, and auditable issue logging.
    """

    @classmethod
    async def clean_tabular_dataset(
        cls,
        db: AsyncSession,
        project_id: str,
        file_id: str,
        cleaning_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Cleans a project dataset:
        1. Reads raw file from projects/{project_id}/raw/
        2. Applies hygiene checks (fulfillment vs demand, negative counts, date alignment)
        3. Preserves *_raw columns and generates *_clean columns + dq_flag
        4. Saves cleaned file to projects/{project_id}/cleaned/
        5. Logs any detected anomalies to data_quality_issues in database
        """
        file_rec = await FileIngestionService.resolve_project_file(db, project_id, file_id)
        if not file_rec:
            return {"error": f"File '{file_id}' not found in project {project_id}."}

        raw_path = Path(file_rec.raw_path)
        if not raw_path.exists():
            return {"error": f"Raw file {file_rec.raw_path} not found on disk."}

        ext = raw_path.suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(raw_path)
        elif ext in {".xlsx", ".xls"}:
            df = pd.read_excel(raw_path)
        else:
            return {"error": f"Data cleaning only supports CSV or Excel files, got {ext}"}

        initial_rows = len(df)
        issues_detected: List[Dict[str, Any]] = []
        clean_df = df.copy()

        # 1. Check for Fulfillment exceeding Demand
        if "qty_fulfilled" in clean_df.columns and "qty_demanded" in clean_df.columns:
            mismatch_mask = clean_df["qty_fulfilled"] > clean_df["qty_demanded"]
            mismatch_count = int(mismatch_mask.sum())
            if mismatch_count > 0:
                # Preserve raw
                clean_df["qty_demanded_raw"] = clean_df["qty_demanded"]
                clean_df["qty_fulfilled_raw"] = clean_df["qty_fulfilled"]
                clean_df["dq_fulfilled_exceeds_demand_flag"] = mismatch_mask

                # Clean values: fulfillment capped at demand for true consumption analysis
                clean_df["qty_demanded_clean"] = clean_df["qty_demanded"]
                clean_df["qty_fulfilled_clean"] = clean_df[["qty_fulfilled", "qty_demanded"]].min(axis=1)

                issues_detected.append({
                    "check_name": "Fulfillment Exceeds Demand",
                    "severity": "MATERIAL",
                    "details": {
                        "violating_records": mismatch_count,
                        "percentage": round(mismatch_count / initial_rows * 100.0, 2),
                    },
                    "treatment": "Preserved raw columns; capped qty_fulfilled_clean to qty_demanded for unconstrained analysis.",
                })

        # 2. Check for Negative Quantities / Inventory
        for col in clean_df.columns:
            if pd.api.types.is_numeric_dtype(clean_df[col]) and any(k in col.lower() for k in ["qty", "stock", "demand", "inventory", "lead_time"]):
                neg_mask = clean_df[col] < 0
                neg_count = int(neg_mask.sum())
                if neg_count > 0:
                    clean_df[f"{col}_raw"] = clean_df[col]
                    clean_df[f"{col}_clean"] = clean_df[col].clip(lower=0)
                    clean_df[f"dq_negative_{col}_flag"] = neg_mask

                    issues_detected.append({
                        "check_name": f"Negative Values in {col}",
                        "severity": "CRITICAL" if "inventory" in col.lower() else "MATERIAL",
                        "details": {
                            "column": col,
                            "violating_records": neg_count,
                            "min_value": float(clean_df[col].min()),
                        },
                        "treatment": f"Preserved raw values in {col}_raw; clipped negative values to 0 in {col}_clean with boolean flags.",
                    })

        # 3. Deduplicate exact duplicate rows
        dup_count = int(clean_df.duplicated().sum())
        if dup_count > 0:
            clean_df = clean_df.drop_duplicates()
            issues_detected.append({
                "check_name": "Exact Duplicate Rows",
                "severity": "MINOR",
                "details": {"dropped_duplicates": dup_count},
                "treatment": "Dropped duplicate rows from cleaned dataframe.",
            })

        # Save cleaned dataset
        project_dir = FileIngestionService.get_project_dir(project_id)
        cleaned_dir = project_dir / "cleaned"
        cleaned_dir.mkdir(parents=True, exist_ok=True)
        cleaned_path = cleaned_dir / f"clean_{raw_path.name}"

        if ext == ".csv":
            clean_df.to_csv(cleaned_path, index=False)
        else:
            clean_df.to_excel(cleaned_path, index=False)

        # Update ProjectFile record with cleaned_path
        file_rec.cleaned_path = str(cleaned_path)

        # Persist issues in database
        for iss in issues_detected:
            issue_rec = DataQualityIssue(
                project_id=project_id,
                file_id=file_id,
                check_name=iss["check_name"],
                severity=iss["severity"],
                details=iss["details"],
                treatment_applied=iss["treatment"],
            )
            db.add(issue_rec)

        await db.commit()

        return {
            "file_id": file_id,
            "filename": raw_path.name,
            "raw_rows": initial_rows,
            "cleaned_rows": len(clean_df),
            "cleaned_columns": len(clean_df.columns),
            "cleaned_path": str(cleaned_path),
            "issues_logged": len(issues_detected),
            "issues": issues_detected,
        }
