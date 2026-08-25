import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from app.schemas.file import ColumnProfile, FileProfileSummary


class DatasetProfiler:
    """Performs deterministic statistical and structural profiling on tabular datasets."""

    @classmethod
    def profile_tabular_file(
        cls,
        file_path: Path,
        file_id: str,
        business_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> FileProfileSummary:
        """
        Profiles a tabular CSV/Excel dataset without transferring massive payloads to LLM.
        """
        ext = file_path.suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(file_path)
        elif ext in {".xlsx", ".xls"}:
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"Profiling only supports tabular files (.csv, .xlsx, .xls), got {ext}")

        total_rows = len(df)
        total_cols = len(df.columns)
        duplicate_rows = int(df.duplicated().sum())

        column_profiles: List[ColumnProfile] = []
        potential_grain: List[str] = []
        quality_alerts: List[str] = []
        date_coverage: Optional[Dict[str, Any]] = None

        for col in df.columns:
            series = df[col]
            null_count = int(series.isnull().sum())
            null_pct = round((null_count / total_rows) * 100.0, 2) if total_rows > 0 else 0.0
            unique_count = int(series.nunique(dropna=True))

            is_key = (unique_count == total_rows) and (null_count == 0) and (total_rows > 0)
            if is_key:
                potential_grain.append(col)

            # Sample non-null values
            valid_samples = series.dropna().unique()[:5].tolist()
            sample_values = [str(v) if not isinstance(v, (int, float, bool)) else v for v in valid_samples]

            numeric_stats: Optional[Dict[str, float]] = None
            if pd.api.types.is_numeric_dtype(series):
                clean_num = series.dropna()
                if len(clean_num) > 0:
                    numeric_stats = {
                        "min": float(np.round(clean_num.min(), 4)),
                        "max": float(np.round(clean_num.max(), 4)),
                        "mean": float(np.round(clean_num.mean(), 4)),
                        "median": float(np.round(clean_num.median(), 4)),
                        "std": float(np.round(clean_num.std(), 4)) if len(clean_num) > 1 else 0.0,
                        "q25": float(np.round(clean_num.quantile(0.25), 4)),
                        "q75": float(np.round(clean_num.quantile(0.75), 4)),
                    }
                    if (clean_num < 0).any() and ("qty" in col.lower() or "inventory" in col.lower() or "demand" in col.lower()):
                        quality_alerts.append(f"Negative values detected in quantity/inventory column '{col}'")

            # Check temporal columns
            if pd.api.types.is_datetime64_any_dtype(series) or "date" in col.lower() or "week" in col.lower():
                try:
                    dt_series = pd.to_datetime(series.dropna(), errors="coerce")
                    valid_dts = dt_series.dropna()
                    if len(valid_dts) > 0:
                        min_date = valid_dts.min().isoformat()
                        max_date = valid_dts.max().isoformat()
                        date_coverage = {
                            "date_column": col,
                            "earliest_date": min_date,
                            "latest_date": max_date,
                            "unique_periods": int(valid_dts.nunique()),
                        }
                except Exception:
                    pass

            if null_pct > 20.0:
                quality_alerts.append(f"High missingness in '{col}': {null_pct}% nulls")

            column_profiles.append(
                ColumnProfile(
                    name=str(col),
                    dtype=str(series.dtype),
                    null_count=null_count,
                    null_percentage=null_pct,
                    unique_count=unique_count,
                    sample_values=sample_values,
                    numeric_stats=numeric_stats,
                    is_key_candidate=is_key,
                )
            )

        # Custom business rules check
        if business_rules:
            for rule in business_rules:
                expr = rule.get("expression")
                rule_name = rule.get("name", expr)
                if expr and all(c in df.columns for c in rule.get("columns", [])):
                    try:
                        violating = df.query(f"not ({expr})")
                        if len(violating) > 0:
                            quality_alerts.append(
                                f"Business rule '{rule_name}' violated by {len(violating)} records ({round(len(violating)/total_rows*100, 2)}%)"
                            )
                    except Exception as e:
                        quality_alerts.append(f"Failed to evaluate rule '{rule_name}': {e}")

        summary = FileProfileSummary(
            file_id=file_id,
            filename=file_path.name,
            row_count=total_rows,
            column_count=total_cols,
            columns=column_profiles,
            duplicate_rows_count=duplicate_rows,
            date_coverage=date_coverage,
            potential_grain=potential_grain,
            quality_alerts=quality_alerts,
        )

        # Save profile artifact into project outputs
        project_dir = file_path.parent.parent
        outputs_dir = project_dir / "outputs"
        if outputs_dir.exists():
            report_path = outputs_dir / f"DATA_QUALITY_{file_path.stem}.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(summary.model_dump(), f, indent=2)

        return summary
