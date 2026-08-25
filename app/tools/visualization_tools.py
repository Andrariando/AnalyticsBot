import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import matplotlib
matplotlib.use("Agg")  # Headless backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Artifact
from app.tools.file_tools import FileIngestionService


class ChartGenerationTool:
    """
    Produces publication-grade, decision-oriented charts for executives and planners.
    """

    @classmethod
    async def create_pareto_chart(
        cls,
        db: AsyncSession,
        project_id: str,
        df_skus: pd.DataFrame,
        sku_col: str = "sku",
        dollar_col: str = "annual_dollar_volume",
        unit_col: Optional[str] = "annual_unit_volume",
        chart_title: str = "SKU Velocity Concentration (Pareto Analysis)",
    ) -> Dict[str, Any]:
        """
        Builds a Pareto curve comparing cumulative dollar volume against unit volume.
        """
        project_dir = FileIngestionService.initialize_project_workspace(project_id)
        charts_dir = project_dir / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        chart_path = charts_dir / "pareto_velocity_curve.png"

        df_sorted = df_skus.sort_values(by=dollar_col, ascending=False).reset_index(drop=True)
        df_sorted["cum_dollar_pct"] = (df_sorted[dollar_col].cumsum() / df_sorted[dollar_col].sum()) * 100.0
        df_sorted["sku_pct"] = ((df_sorted.index + 1) / len(df_sorted)) * 100.0

        fig, ax = plt.subplots(figsize=(10, 6), dpi=300)

        # Plot Dollar Pareto Curve
        ax.plot(
            df_sorted["sku_pct"],
            df_sorted["cum_dollar_pct"],
            color="#1E3A8A",
            linewidth=2.5,
            label="Cumulative Dollar Volume (%)",
        )

        # Plot Unit Curve if provided
        if unit_col and unit_col in df_sorted.columns:
            df_unit_sorted = df_skus.sort_values(by=unit_col, ascending=False).reset_index(drop=True)
            df_unit_sorted["cum_unit_pct"] = (df_unit_sorted[unit_col].cumsum() / df_unit_sorted[unit_col].sum()) * 100.0
            df_unit_sorted["sku_pct"] = ((df_unit_sorted.index + 1) / len(df_unit_sorted)) * 100.0
            ax.plot(
                df_unit_sorted["sku_pct"],
                df_unit_sorted["cum_unit_pct"],
                color="#059669",
                linewidth=2.0,
                linestyle="--",
                label="Cumulative Unit Volume (%)",
            )

        # 80/20 Reference Lines
        ax.axhline(80, color="#DC2626", linestyle=":", linewidth=1.5, label="Class A Cutoff (80% Dollar Volume)")
        ax.axhline(95, color="#D97706", linestyle=":", linewidth=1.2, label="Class B Cutoff (95% Dollar Volume)")

        # Grid and formatting
        ax.set_title(chart_title, fontsize=14, fontweight="bold", pad=15)
        ax.set_xlabel("Cumulative Percentage of SKUs (%)", fontsize=11)
        ax.set_ylabel("Cumulative Volume Share (%)", fontsize=11)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 105)
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend(loc="lower right", frameon=True, facecolor="white", framealpha=0.9)

        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)

        # Record in artifacts table
        art = Artifact(
            project_id=project_id,
            artifact_type="CHART",
            file_path=str(chart_path),
            summary="Pareto Concentration Analysis comparing Dollar vs Unit Velocity across SKUs.",
        )
        db.add(art)
        await db.commit()

        return {
            "chart_type": "PARETO_CURVE",
            "file_path": str(chart_path),
            "summary": "Pareto curve generated showing SKU concentration and ABC cutoffs.",
        }

    @classmethod
    async def create_inventory_vs_target_chart(
        cls,
        db: AsyncSession,
        project_id: str,
        df_inventory: pd.DataFrame,
        sku_col: str = "sku",
        current_wos_col: str = "current_wos",
        target_wos_col: str = "target_wos",
        chart_title: str = "Current Coverage vs Target Stocking Policy (Weeks of Supply)",
    ) -> Dict[str, Any]:
        """
        Compares actual weeks of supply against recommended target stocking policies.
        """
        project_dir = FileIngestionService.initialize_project_workspace(project_id)
        charts_dir = project_dir / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        chart_path = charts_dir / "inventory_vs_target_wos.png"

        sample_df = df_inventory.head(30).copy()
        x = np.arange(len(sample_df))
        width = 0.38

        fig, ax = plt.subplots(figsize=(12, 6), dpi=300)

        ax.bar(x - width/2, sample_df[current_wos_col], width, label="Current WOS", color="#3B82F6", alpha=0.85)
        ax.bar(x + width/2, sample_df[target_wos_col], width, label="Target WOS", color="#10B981", alpha=0.85)

        ax.axhline(4, color="#EF4444", linestyle="--", linewidth=1.2, label="Stockout Risk Threshold (4 WOS)")
        ax.axhline(26, color="#F59E0B", linestyle="--", linewidth=1.2, label="Excess Inventory Threshold (26 WOS)")

        ax.set_title(chart_title, fontsize=14, fontweight="bold", pad=15)
        ax.set_xlabel("SKU Sample", fontsize=11)
        ax.set_ylabel("Weeks of Supply (WOS)", fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(sample_df[sku_col], rotation=45, ha="right", fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.4, axis="y")
        ax.legend(loc="upper right", frameon=True)

        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)

        art = Artifact(
            project_id=project_id,
            artifact_type="CHART",
            file_path=str(chart_path),
            summary="Coverage analysis comparing current Weeks of Supply against Target Stocking Policies.",
        )
        db.add(art)
        await db.commit()

        return {
            "chart_type": "INVENTORY_VS_TARGET",
            "file_path": str(chart_path),
            "summary": "Inventory coverage chart saved showing overstocked vs understocked nodes.",
        }

    @classmethod
    async def create_capacity_utilization_chart(
        cls,
        db: AsyncSession,
        project_id: str,
        df_warehouses: pd.DataFrame,
        dc_col: str = "dc_code",
        occupied_col: str = "occupied_pallets",
        capacity_col: str = "dedicated_pallet_capacity",
        chart_title: str = "Warehouse Pallet Capacity Utilization by DC",
    ) -> Dict[str, Any]:
        """
        Bar chart showing DC dedicated pallet occupancy vs capacity threshold.
        """
        project_dir = FileIngestionService.initialize_project_workspace(project_id)
        charts_dir = project_dir / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        chart_path = charts_dir / "warehouse_capacity_utilization.png"

        fig, ax = plt.subplots(figsize=(9, 5), dpi=300)

        dcs = df_warehouses[dc_col]
        occupied = df_warehouses[occupied_col]
        capacity = df_warehouses[capacity_col]

        util_pct = (occupied / capacity) * 100.0
        colors = ["#DC2626" if u >= 90 else "#3B82F6" for u in util_pct]

        bars = ax.bar(dcs, occupied, color=colors, alpha=0.85, label="Occupied Pallets")
        ax.plot(dcs, capacity, color="#111827", marker="o", linewidth=2, label="Dedicated Pallet Limit")

        # Value annotations
        for bar, u in zip(bars, util_pct):
            yval = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2.0, yval + 1, f"{int(yval)} ({u:.1f}%)", ha="center", va="bottom", fontsize=9, fontweight="bold")

        ax.set_title(chart_title, fontsize=13, fontweight="bold", pad=15)
        ax.set_xlabel("Distribution Center (DC)", fontsize=11)
        ax.set_ylabel("Pallet Positions", fontsize=11)
        ax.grid(True, linestyle="--", alpha=0.4, axis="y")
        ax.legend(loc="lower right")

        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)

        art = Artifact(
            project_id=project_id,
            artifact_type="CHART",
            file_path=str(chart_path),
            summary="Warehouse pallet capacity utilization chart highlighting DC bottleneck risks.",
        )
        db.add(art)
        await db.commit()

        return {
            "chart_type": "CAPACITY_UTILIZATION",
            "file_path": str(chart_path),
            "summary": "Capacity utilization chart generated highlighting DC space bottlenecks.",
        }
