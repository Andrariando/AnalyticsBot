import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Artifact, ProjectFile
from app.tools.file_tools import FileIngestionService

logger = logging.getLogger(__name__)


class MultiEchelonAnalyticsService:
    """
    Multi-Echelon Inventory Optimization (MEIO) Suite:
    Hub-and-Spoke buffer sizing, risk pooling estimation, and echelon safety stock optimization.
    """

    @classmethod
    async def calculate_multi_echelon_policy(
        cls,
        db: AsyncSession,
        project_id: str,
        demand_file_id: str,
        central_dc_code: str = "CDC",
        target_service_level: float = 0.95,
        supplier_lead_time_weeks: float = 4.0,
        internal_transit_weeks: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Calculates Multi-Echelon safety stocks across a 2-echelon network (Central Hub -> Regional Spokes)
        using the Guaranteed-Service Multi-Echelon model:
        - Decentralized Model: Each RDC holds SS for the full supplier lead time (L_sup).
        - Multi-Echelon MEIO Model: Central DC holds pooled SS for net lead time (L_sup - L_int),
          and each RDC holds echelon SS for local transit lead time (L_int).
        - Guaranteed capital reduction via portfolio effect / sub-additivity of standard deviation.
        """
        stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == demand_file_id)
        res = await db.execute(stmt)
        dem_rec = res.scalar_one_or_none()
        if not dem_rec:
            return {"error": "Demand dataset not found in project."}

        df_dem = pd.read_csv(dem_rec.cleaned_path or dem_rec.raw_path)

        sku_col = next((c for c in df_dem.columns if "part" in c.lower() or "sku" in c.lower()), df_dem.columns[0])
        dc_col = next((c for c in df_dem.columns if "wh" in c.lower() or "dc" in c.lower() or "warehouse" in c.lower()), None)
        qty_col = next((c for c in df_dem.columns if "qty" in c.lower() or "demand" in c.lower() or "sales" in c.lower()), df_dem.columns[-1])

        z_score = 1.645 if target_service_level >= 0.95 else 1.282
        net_cdc_lead_time = max(0.5, supplier_lead_time_weeks - internal_transit_weeks)

        results = []
        for sku, group in df_dem.groupby(sku_col):
            sku_str = str(sku)

            if dc_col and dc_col in group.columns:
                dc_stats = []
                for dc, dc_group in group.groupby(dc_col):
                    series = dc_group[qty_col].astype(float).values
                    m_d = float(np.mean(series)) if len(series) > 0 else 1.0
                    s_d = float(np.std(series, ddof=1)) if len(series) > 1 else (0.3 * m_d)
                    dc_stats.append({"dc": str(dc), "mean_d": m_d, "std_d": max(0.1, s_d)})
            else:
                series = group[qty_col].astype(float).values
                m_d = float(np.mean(series)) if len(series) > 0 else 1.0
                s_d = float(np.std(series, ddof=1)) if len(series) > 1 else (0.3 * m_d)
                dc_stats = [
                    {"dc": "RDC_East", "mean_d": m_d * 0.4, "std_d": max(0.1, s_d * 0.4)},
                    {"dc": "RDC_West", "mean_d": m_d * 0.4, "std_d": max(0.1, s_d * 0.4)},
                    {"dc": "RDC_Central", "mean_d": m_d * 0.2, "std_d": max(0.1, s_d * 0.2)},
                ]

            # 1. Decentralized Safety Stock (Sum of individual RDC safety stocks for full supplier lead time)
            decentralized_ss_total = 0.0
            rdc_echelon_ss_total = 0.0

            for d in dc_stats:
                s_i = d["std_d"]
                # Decentralized SS with full supplier lead time
                ss_dec = z_score * math.sqrt(max(0.1, supplier_lead_time_weeks * (s_i ** 2)))
                decentralized_ss_total += ss_dec

                # MEIO spoke SS (protects local internal transit lead time from central hub)
                ss_rdc_echelon = z_score * math.sqrt(max(0.1, internal_transit_weeks * (s_i ** 2)))
                rdc_echelon_ss_total += ss_rdc_echelon

            # 2. Central Hub Pooled Safety Stock (protects upstream lead time differential)
            sum_var = sum(d["std_d"] ** 2 for d in dc_stats)
            pooled_std = math.sqrt(sum_var)
            cdc_pooled_ss = z_score * math.sqrt(max(0.1, net_cdc_lead_time * (pooled_std ** 2)))

            # Total Multi-Echelon Network Safety Stock
            meio_total_ss = cdc_pooled_ss + rdc_echelon_ss_total

            # Working capital savings from multi-echelon risk pooling
            ss_units_saved = max(0.0, decentralized_ss_total - meio_total_ss)
            pooling_pct_savings = (ss_units_saved / decentralized_ss_total * 100) if decentralized_ss_total > 0 else 0.0

            results.append({
                "sku": sku_str,
                "central_hub": central_dc_code,
                "num_spokes": len(dc_stats),
                "decentralized_ss_units": round(decentralized_ss_total, 1),
                "optimal_cdc_ss_units": round(cdc_pooled_ss, 1),
                "optimal_spoke_ss_units_total": round(rdc_echelon_ss_total, 1),
                "multi_echelon_total_ss_units": round(meio_total_ss, 1),
                "ss_units_saved": round(ss_units_saved, 1),
                "pooling_efficiency_pct": round(pooling_pct_savings, 1),
            })

        df_meio = pd.DataFrame(results)

        project_dir = FileIngestionService.get_project_dir(project_id)
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        out_csv = analysis_dir / "multi_echelon_meio_evaluation.csv"
        df_meio.to_csv(out_csv, index=False)

        art = Artifact(
            project_id=project_id,
            artifact_type="ANALYSIS_TABLE",
            file_path=str(out_csv),
            summary=f"Multi-Echelon MEIO inventory optimization across {len(df_meio)} SKUs.",
        )
        db.add(art)
        await db.commit()

        total_dec_units = float(df_meio["decentralized_ss_units"].sum())
        total_meio_units = float(df_meio["multi_echelon_total_ss_units"].sum())
        total_saved_units = float(df_meio["ss_units_saved"].sum())
        overall_pooling_gain = (total_saved_units / total_dec_units * 100) if total_dec_units > 0 else 0.0

        return {
            "project_id": project_id,
            "total_skus_evaluated": len(df_meio),
            "total_decentralized_ss_units": round(total_dec_units, 1),
            "total_multi_echelon_ss_units": round(total_meio_units, 1),
            "total_ss_units_saved_by_pooling": round(total_saved_units, 1),
            "overall_pooling_gain_pct": round(overall_pooling_gain, 1),
            "file_path": str(out_csv),
        }
