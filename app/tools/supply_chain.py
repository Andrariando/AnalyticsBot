import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.stats import norm
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Artifact, ProjectFile
from app.tools.file_tools import FileIngestionService


class SupplyChainAnalyticsService:
    """
    Comprehensive Supply Chain & Operations Research Analytical Suite:
    1. Velocity & Demand Pattern Segmentation (ABC, XYZ, Syntetos-Boylan ADI/CV2)
    2. Dynamic Stocking Policy (Safety Stock, ROP, Order-Up-To, Target WOS, Excess/Shortage)
    3. Lateral Multi-DC Network Rebalancing Optimization
    4. Lifecycle Disposition Engine (Vendor Returns, Liquidation, Scrap)
    """

    @classmethod
    async def calculate_velocity_segmentation(
        cls,
        db: AsyncSession,
        project_id: str,
        demand_file_id: str,
        parts_file_id: Optional[str] = None,
        demand_window_weeks: int = 26,
    ) -> Dict[str, Any]:
        """
        Executes multi-dimensional demand classification:
        - ABC Dollar Velocity (80/15/5%)
        - ABC Unit Velocity (to highlight mix/velocity divergence)
        - XYZ Demand Variability (Coefficient of Variation)
        - Syntetos-Boylan Intermittency Classification (ADI vs CV2)
        """
        from sqlalchemy import select

        # Load demand file
        stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == demand_file_id)
        res = await db.execute(stmt)
        demand_rec = res.scalar_one_or_none()
        if not demand_rec:
            return {"error": f"Demand file {demand_file_id} not found."}

        demand_path = Path(demand_rec.cleaned_path or demand_rec.raw_path)
        df_demand = pd.read_csv(demand_path)

        # Standardize column names
        col_map = {c: c.lower() for c in df_demand.columns}
        df_demand.rename(columns=col_map, inplace=True)

        sku_col = next((c for c in df_demand.columns if "sku" in c or "part" in c), None)
        qty_col = next((c for c in df_demand.columns if "demand" in c or "qty" in c), None)
        week_col = next((c for c in df_demand.columns if "week" in c or "date" in c), None)

        if not sku_col or not qty_col:
            return {"error": f"Could not identify SKU and Demand columns in {demand_path.name}"}

        # Filter by recent demand window if week column available
        if week_col:
            df_demand[week_col] = pd.to_datetime(df_demand[week_col], errors="coerce")
            max_date = df_demand[week_col].max()
            min_cutoff = max_date - pd.Timedelta(weeks=demand_window_weeks)
            df_demand = df_demand[df_demand[week_col] >= min_cutoff].copy()

        # Load unit costs if parts file provided
        parts_cost_map: Dict[str, float] = {}
        if parts_file_id:
            p_stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == parts_file_id)
            p_res = await db.execute(p_stmt)
            p_rec = p_res.scalar_one_or_none()
            if p_rec:
                df_parts = pd.read_csv(p_rec.cleaned_path or p_rec.raw_path)
                df_parts.rename(columns={c: c.lower() for c in df_parts.columns}, inplace=True)
                p_sku = next((c for c in df_parts.columns if "sku" in c or "part" in c), None)
                p_cost = next((c for c in df_parts.columns if "cost" in c or "price" in c), None)
                if p_sku and p_cost:
                    parts_cost_map = dict(zip(df_parts[p_sku], pd.to_numeric(df_parts[p_cost], errors="coerce").fillna(10.0)))

        # Aggregate by SKU
        sku_groups = df_demand.groupby(sku_col)[qty_col]
        total_units = sku_groups.sum()
        mean_demand = sku_groups.mean()
        std_demand = sku_groups.std(ddof=1).fillna(0.0)

        # Syntetos-Boylan metrics
        # ADI = Total Periods / Non-Zero Demand Periods
        # CV2 = (std_non_zero / mean_non_zero)^2
        def calc_sb_metrics(series: pd.Series) -> Tuple[float, float, str]:
            total_periods = len(series)
            non_zero = series[series > 0]
            non_zero_periods = len(non_zero)
            if non_zero_periods == 0:
                return 999.0, 999.0, "Lumpy"

            adi = total_periods / non_zero_periods
            mean_nz = non_zero.mean()
            std_nz = non_zero.std(ddof=1) if non_zero_periods > 1 else 0.0
            cv2 = float((std_nz / mean_nz) ** 2) if mean_nz > 0 else 0.0

            # Quadrant assignment (Cutoffs: ADI=1.32, CV2=0.49)
            if adi < 1.32 and cv2 < 0.49:
                pattern = "Smooth"
            elif adi < 1.32 and cv2 >= 0.49:
                pattern = "Erratic"
            elif adi >= 1.32 and cv2 < 0.49:
                pattern = "Intermittent"
            else:
                pattern = "Lumpy"

            return round(adi, 2), round(cv2, 4), pattern

        sb_results = {sku: calc_sb_metrics(group) for sku, group in sku_groups}

        df_summary = pd.DataFrame({
            "sku": total_units.index,
            "unit_demand": total_units.values,
            "mean_weekly_demand": mean_demand.values.round(2),
            "std_weekly_demand": std_demand.values.round(2),
        })

        # Calculate dollar demand
        df_summary["unit_cost"] = df_summary["sku"].map(lambda s: parts_cost_map.get(s, 15.0))
        df_summary["dollar_demand"] = (df_summary["unit_demand"] * df_summary["unit_cost"]).round(2)

        # ABC Dollar Segmentation (80/15/5%)
        df_summary = df_summary.sort_values(by="dollar_demand", ascending=False).reset_index(drop=True)
        total_dollar = df_summary["dollar_demand"].sum()
        df_summary["cum_dollar_pct"] = (df_summary["dollar_demand"].cumsum() / (total_dollar if total_dollar > 0 else 1.0)) * 100.0
        df_summary["abc_dollar"] = pd.cut(
            df_summary["cum_dollar_pct"],
            bins=[-np.inf, 80.0, 95.0, 100.0],
            labels=["A", "B", "C"],
        ).astype(str)

        # ABC Unit Segmentation
        df_summary = df_summary.sort_values(by="unit_demand", ascending=False).reset_index(drop=True)
        total_unit_vol = df_summary["unit_demand"].sum()
        df_summary["cum_unit_pct"] = (df_summary["unit_demand"].cumsum() / (total_unit_vol if total_unit_vol > 0 else 1.0)) * 100.0
        df_summary["abc_unit"] = pd.cut(
            df_summary["cum_unit_pct"],
            bins=[-np.inf, 80.0, 95.0, 100.0],
            labels=["A", "B", "C"],
        ).astype(str)

        # XYZ Segmentation (CV = std / mean)
        df_summary["cv"] = np.where(df_summary["mean_weekly_demand"] > 0, df_summary["std_weekly_demand"] / df_summary["mean_weekly_demand"], 99.0).round(2)
        df_summary["xyz_class"] = pd.cut(
            df_summary["cv"],
            bins=[-np.inf, 0.5, 1.0, np.inf],
            labels=["X", "Y", "Z"],
        ).astype(str)

        # Add Syntetos-Boylan fields
        df_summary["adi"] = df_summary["sku"].map(lambda s: sb_results.get(s, (0, 0, ""))[0])
        df_summary["cv2"] = df_summary["sku"].map(lambda s: sb_results.get(s, (0, 0, ""))[1])
        df_summary["demand_pattern"] = df_summary["sku"].map(lambda s: sb_results.get(s, (0, 0, ""))[2])

        # Combined Velocity Class (e.g. AX-Smooth, CZ-Lumpy)
        df_summary["velocity_tier"] = df_summary["abc_dollar"] + df_summary["xyz_class"]

        # Save segmentation output table to project
        project_dir = FileIngestionService.get_project_dir(project_id)
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        out_csv_path = analysis_dir / "sku_velocity_segmentation.csv"
        df_summary.to_csv(out_csv_path, index=False)

        # Register artifact
        art = Artifact(
            project_id=project_id,
            artifact_type="ANALYSIS_TABLE",
            file_path=str(out_csv_path),
            summary="SKU Velocity Segmentation Table containing ABC (Dollar & Unit), XYZ, ADI, CV2, and Syntetos-Boylan classes.",
        )
        db.add(art)
        await db.commit()

        # Breakdown stats for concise agent reasoning
        abc_breakdown = df_summary["abc_dollar"].value_counts().to_dict()
        pattern_breakdown = df_summary["demand_pattern"].value_counts().to_dict()

        return {
            "total_skus": len(df_summary),
            "total_dollar_demand": round(float(total_dollar), 2),
            "total_unit_demand": int(total_unit_vol),
            "abc_dollar_distribution": abc_breakdown,
            "demand_pattern_distribution": pattern_breakdown,
            "artifact_path": str(out_csv_path),
            "sample_records": df_summary.head(5).to_dict(orient="records"),
        }

    @classmethod
    async def calculate_stocking_policy(
        cls,
        db: AsyncSession,
        project_id: str,
        inventory_file_id: str,
        demand_file_id: str,
        parts_file_id: Optional[str] = None,
        warehouses_file_id: Optional[str] = None,
        target_service_levels: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Calculates dynamic stocking policies (Safety Stock, ROP, Order-Up-To, Target WOS)
        and quantifies current excess, shortages, holding costs, and working capital impact.
        """
        from sqlalchemy import select

        # Default service level policy by ABC tier
        sl_map = target_service_levels or {"A": 0.95, "B": 0.90, "C": 0.85}

        # 1. Load Inventory Snapshot
        i_stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == inventory_file_id)
        inv_rec = (await db.execute(i_stmt)).scalar_one_or_none()
        if not inv_rec:
            return {"error": f"Inventory file {inventory_file_id} not found."}

        df_inv = pd.read_csv(inv_rec.cleaned_path or inv_rec.raw_path)
        df_inv.rename(columns={c: c.lower() for c in df_inv.columns}, inplace=True)

        # 2. Load Demand File
        d_stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == demand_file_id)
        dem_rec = (await db.execute(d_stmt)).scalar_one_or_none()
        df_dem = pd.read_csv(dem_rec.cleaned_path or dem_rec.raw_path)
        df_dem.rename(columns={c: c.lower() for c in df_dem.columns}, inplace=True)

        sku_col = next((c for c in df_inv.columns if "sku" in c or "part" in c), "part_number")
        dc_col = next((c for c in df_inv.columns if "dc" in c or "warehouse" in c), "warehouse_id")
        on_hand_col = next((c for c in df_inv.columns if "hand" in c or "stock" in c), "on_hand_units")
        on_order_col = next((c for c in df_inv.columns if "order" in c), "on_order_units")
        dem_qty_col = next((c for c in df_dem.columns if "demand" in c or "qty" in c), "qty_demanded")

        # Load parts master (cost, lead time)
        parts_info: Dict[str, Dict[str, Any]] = {}
        if parts_file_id:
            p_stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == parts_file_id)
            p_rec = (await db.execute(p_stmt)).scalar_one_or_none()
            if p_rec:
                df_parts = pd.read_csv(p_rec.cleaned_path or p_rec.raw_path)
                df_parts.rename(columns={c: c.lower() for c in df_parts.columns}, inplace=True)
                p_sku = next((c for c in df_parts.columns if "sku" in c or "part" in c), "part_number")
                p_cost = next((c for c in df_parts.columns if "cost" in c or "price" in c), "unit_cost")
                p_lt = next((c for c in df_parts.columns if "lead" in c), "lead_time_days")
                p_life = next((c for c in df_parts.columns if "life" in c), "lifecycle_status")
                p_ret = next((c for c in df_parts.columns if "return" in c), "return_eligible")

                for _, row in df_parts.iterrows():
                    parts_info[str(row[p_sku])] = {
                        "unit_cost": float(row.get(p_cost, 25.0)),
                        "lead_time_days": float(row.get(p_lt, 28.0)),
                        "lead_time_weeks": max(1.0, float(row.get(p_lt, 28.0)) / 7.0),
                        "lifecycle": str(row.get(p_life, "ACTIVE")),
                        "return_eligible": bool(row.get(p_ret, True)),
                    }

        # Calculate demand stats per SKU × DC
        dem_stats = df_dem.groupby([sku_col, dc_col])[dem_qty_col].agg(["mean", "std"]).reset_index()
        dem_stats.rename(columns={"mean": "mean_weekly_demand", "std": "std_weekly_demand"}, inplace=True)
        dem_stats["std_weekly_demand"] = dem_stats["std_weekly_demand"].fillna(0.0)

        # Merge with inventory snapshot (using most recent snapshot if multiple weeks present)
        week_col = next((c for c in df_inv.columns if "week" in c or "date" in c), None)
        if week_col:
            df_inv[week_col] = pd.to_datetime(df_inv[week_col], errors="coerce")
            max_inv_date = df_inv[week_col].max()
            df_inv_current = df_inv[df_inv[week_col] == max_inv_date].copy()
        else:
            df_inv_current = df_inv.copy()

        df_policy = pd.merge(df_inv_current, dem_stats, on=[sku_col, dc_col], how="left")
        df_policy["mean_weekly_demand"] = df_policy["mean_weekly_demand"].fillna(0.1)
        df_policy["std_weekly_demand"] = df_policy["std_weekly_demand"].fillna(0.1)

        # Compute dynamic safety stock and ROP
        results = []
        for _, row in df_policy.iterrows():
            sku = str(row[sku_col])
            dc = str(row[dc_col])
            oh = float(row.get(on_hand_col, 0.0))
            oo = float(row.get(on_order_col, 0.0))
            inv_pos = oh + oo
            d_mean = float(row["mean_weekly_demand"])
            d_std = float(row["std_weekly_demand"])

            p_meta = parts_info.get(sku, {
                "unit_cost": 25.0,
                "lead_time_days": 28.0,
                "lead_time_weeks": 4.0,
                "lifecycle": "ACTIVE",
                "return_eligible": True,
            })

            lt_weeks = p_meta["lead_time_weeks"]
            unit_cost = p_meta["unit_cost"]

            # Service level target by demand volume (ABC heuristic)
            annual_dollars = d_mean * 52.0 * unit_cost
            if annual_dollars > 20000:
                tier = "A"
                sl = sl_map.get("A", 0.95)
            elif annual_dollars > 5000:
                tier = "B"
                sl = sl_map.get("B", 0.90)
            else:
                tier = "C"
                sl = sl_map.get("C", 0.85)

            z = norm.ppf(sl)

            # Safety Stock: SS = z * sqrt(L * sigma_d^2)
            ss = z * np.sqrt(lt_weeks * (d_std ** 2))
            ss = max(1.0, round(float(ss), 1))

            # Reorder Point: ROP = D * L + SS
            rop = (d_mean * lt_weeks) + ss
            rop = round(float(rop), 1)

            # Order Up To (S): target coverage = Lead Time + Review Period (e.g. 4 weeks) + SS
            order_up_to = (d_mean * (lt_weeks + 4.0)) + ss
            order_up_to = round(float(order_up_to), 1)

            target_wos = round(order_up_to / (d_mean if d_mean > 0 else 0.1), 1)
            current_wos = round(oh / (d_mean if d_mean > 0 else 0.1), 1)

            excess_units = max(0.0, oh - order_up_to)
            shortage_units = max(0.0, rop - inv_pos)

            excess_dollars = round(excess_units * unit_cost, 2)
            shortage_dollars = round(shortage_units * unit_cost, 2)
            on_hand_dollars = round(oh * unit_cost, 2)

            results.append({
                "sku": sku,
                "dc": dc,
                "unit_cost": unit_cost,
                "lead_time_weeks": lt_weeks,
                "mean_weekly_demand": round(d_mean, 2),
                "std_weekly_demand": round(d_std, 2),
                "abc_tier": tier,
                "service_level_target": sl,
                "on_hand_units": int(oh),
                "on_order_units": int(oo),
                "inventory_position": int(inv_pos),
                "on_hand_dollars": on_hand_dollars,
                "recommended_safety_stock": ss,
                "recommended_rop": rop,
                "recommended_order_up_to": order_up_to,
                "target_wos": target_wos,
                "current_wos": current_wos,
                "excess_units": int(excess_units),
                "excess_dollars": excess_dollars,
                "shortage_units": int(shortage_units),
                "shortage_dollars": shortage_dollars,
                "lifecycle": p_meta["lifecycle"],
                "return_eligible": p_meta["return_eligible"],
            })

        df_out = pd.DataFrame(results)

        # Save policy table
        project_dir = FileIngestionService.get_project_dir(project_id)
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        policy_csv_path = analysis_dir / "stocking_policy_evaluation.csv"
        df_out.to_csv(policy_csv_path, index=False)

        # Register artifact
        art = Artifact(
            project_id=project_id,
            artifact_type="POLICY_EVALUATION",
            file_path=str(policy_csv_path),
            summary="Stocking Policy Table comparing actual inventory positions against recommended Dynamic SS, ROP, Order-Up-To, and WOS.",
        )
        db.add(art)
        await db.commit()

        total_working_capital = df_out["on_hand_dollars"].sum()
        total_excess_capital = df_out["excess_dollars"].sum()
        total_shortage_capital = df_out["shortage_dollars"].sum()

        return {
            "total_nodes_evaluated": len(df_out),
            "total_on_hand_working_capital": round(float(total_working_capital), 2),
            "total_excess_working_capital": round(float(total_excess_capital), 2),
            "total_shortage_value": round(float(total_shortage_capital), 2),
            "overstocked_nodes_count": int((df_out["excess_units"] > 0).sum()),
            "understocked_nodes_count": int((df_out["shortage_units"] > 0).sum()),
            "artifact_path": str(policy_csv_path),
            "top_excess_nodes": df_out.sort_values(by="excess_dollars", ascending=False).head(5)[["sku", "dc", "on_hand_units", "recommended_order_up_to", "excess_dollars"]].to_dict(orient="records"),
            "top_shortage_nodes": df_out.sort_values(by="shortage_dollars", ascending=False).head(5)[["sku", "dc", "on_hand_units", "recommended_rop", "shortage_dollars"]].to_dict(orient="records"),
        }

    @classmethod
    async def generate_rebalance_candidates(
        cls,
        db: AsyncSession,
        project_id: str,
        policy_eval_file_path: Optional[str] = None,
        transfer_lanes_file_id: Optional[str] = None,
        warehouses_file_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Solves lateral multi-DC inventory rebalancing:
        Matches long nodes (Origin DC has excess) with short nodes (Destination DC has shortage)
        under transit lane costs, transit times, and DC pallet capacity constraints.
        """
        from sqlalchemy import select

        # Load policy evaluation table
        if not policy_eval_file_path:
            project_dir = FileIngestionService.get_project_dir(project_id)
            policy_eval_file_path = str(project_dir / "analysis" / "stocking_policy_evaluation.csv")

        if not Path(policy_eval_file_path).exists():
            return {"error": "Stocking policy evaluation file not found. Run calculate_stocking_policy first."}

        df_policy = pd.read_csv(policy_eval_file_path)

        # Load transfer lanes cost matrix
        lane_costs: Dict[Tuple[str, str], Dict[str, float]] = {}
        if transfer_lanes_file_id:
            t_stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == transfer_lanes_file_id)
            t_rec = (await db.execute(t_stmt)).scalar_one_or_none()
            if t_rec:
                df_lanes = pd.read_csv(t_rec.cleaned_path or t_rec.raw_path)
                df_lanes.rename(columns={c: c.lower() for c in df_lanes.columns}, inplace=True)
                o_col = next((c for c in df_lanes.columns if "origin" in c or "from" in c), "origin_dc")
                d_col = next((c for c in df_lanes.columns if "dest" in c or "to" in c), "destination_dc")
                c_col = next((c for c in df_lanes.columns if "cost" in c), "cost_per_unit")
                days_col = next((c for c in df_lanes.columns if "day" in c or "time" in c), "transit_days")

                for _, row in df_lanes.iterrows():
                    lane_costs[(str(row[o_col]), str(row[d_col]))] = {
                        "cost_per_unit": float(row.get(c_col, 5.0)),
                        "transit_days": float(row.get(days_col, 3.0)),
                    }

        # Filter active SKUs with excess at origin and shortage at destination
        rebalance_candidates = []

        # Group by SKU
        for sku, sku_group in df_policy.groupby("sku"):
            long_nodes = sku_group[sku_group["excess_units"] > 0].copy()
            short_nodes = sku_group[sku_group["shortage_units"] > 0].copy()

            if long_nodes.empty or short_nodes.empty:
                continue

            for _, l_node in long_nodes.iterrows():
                origin_dc = str(l_node["dc"])
                avail_excess = float(l_node["excess_units"])
                origin_ss = float(l_node["recommended_safety_stock"])
                origin_oh = float(l_node["on_hand_units"])
                unit_cost = float(l_node["unit_cost"])

                for _, s_node in short_nodes.iterrows():
                    if avail_excess <= 0:
                        break

                    dest_dc = str(s_node["dc"])
                    if origin_dc == dest_dc:
                        continue

                    needed_shortage = float(s_node["shortage_units"])
                    if needed_shortage <= 0:
                        continue

                    # Determine optimal transfer quantity
                    transfer_qty = min(avail_excess, needed_shortage)

                    # Ensure origin remains at or above Safety Stock
                    if (origin_oh - transfer_qty) < origin_ss:
                        transfer_qty = max(0.0, origin_oh - origin_ss)

                    if transfer_qty <= 0:
                        continue

                    # Lookup lane economics
                    lane_info = lane_costs.get((origin_dc, dest_dc), {"cost_per_unit": 4.5, "transit_days": 3.0})
                    est_transfer_cost = round(transfer_qty * lane_info["cost_per_unit"], 2)
                    capital_rebalanced = round(transfer_qty * unit_cost, 2)

                    # WOS after transfer
                    d_mean_dest = float(s_node["mean_weekly_demand"])
                    dest_oh_after = float(s_node["on_hand_units"]) + transfer_qty
                    dest_wos_after = round(dest_oh_after / (d_mean_dest if d_mean_dest > 0 else 0.1), 1)

                    rebalance_candidates.append({
                        "sku": sku,
                        "origin_dc": origin_dc,
                        "destination_dc": dest_dc,
                        "transfer_units": int(transfer_qty),
                        "unit_cost": unit_cost,
                        "rebalanced_asset_value": capital_rebalanced,
                        "estimated_freight_cost": est_transfer_cost,
                        "transit_days": lane_info["transit_days"],
                        "supplier_lead_time_days": float(s_node["lead_time_weeks"]) * 7.0,
                        "dest_wos_after_transfer": dest_wos_after,
                        "economic_category": "INVENTORY_REPOSITIONED",
                        "operational_advantage": f"Transit ({lane_info['transit_days']}d) avoids supplier PO lead time ({int(float(s_node['lead_time_weeks'])*7)}d)",
                    })

                    avail_excess -= transfer_qty

        df_reb = pd.DataFrame(rebalance_candidates)
        if not df_reb.empty:
            df_reb = df_reb.sort_values(by="rebalanced_asset_value", ascending=False).reset_index(drop=True)

        # Save candidate queue
        project_dir = FileIngestionService.get_project_dir(project_id)
        outputs_dir = project_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        reb_csv_path = outputs_dir / "rebalance_action_queue.csv"
        df_reb.to_csv(reb_csv_path, index=False)

        # Register artifact
        art = Artifact(
            project_id=project_id,
            artifact_type="ACTION_QUEUE",
            file_path=str(reb_csv_path),
            summary="Multi-DC Lateral Rebalance Action Queue with freight costs, transit times, and post-transfer WOS.",
        )
        db.add(art)
        await db.commit()

        total_rebalanced_value = df_reb["rebalanced_asset_value"].sum() if not df_reb.empty else 0.0
        total_freight_cost = df_reb["estimated_freight_cost"].sum() if not df_reb.empty else 0.0

        return {
            "total_rebalance_actions": len(df_reb),
            "total_asset_value_repositioned": round(float(total_rebalanced_value), 2),
            "total_freight_investment": round(float(total_freight_cost), 2),
            "artifact_path": str(reb_csv_path),
            "top_transfers": df_reb.head(10).to_dict(orient="records") if not df_reb.empty else [],
        }

    @classmethod
    async def generate_disposition_candidates(
        cls,
        db: AsyncSession,
        project_id: str,
        policy_eval_file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates obsolete, phase-out, or massive-excess inventory for:
        1. Vendor Returns (if return_eligible == True)
        2. Liquidation / Scrap (if return_eligible == False or demand died)
        """
        if not policy_eval_file_path:
            project_dir = FileIngestionService.get_project_dir(project_id)
            policy_eval_file_path = str(project_dir / "analysis" / "stocking_policy_evaluation.csv")

        if not Path(policy_eval_file_path).exists():
            return {"error": "Stocking policy evaluation file not found. Run calculate_stocking_policy first."}

        df_policy = pd.read_csv(policy_eval_file_path)

        disposition_records = []
        for _, row in df_policy.iterrows():
            excess = float(row["excess_units"])
            wos = float(row["current_wos"])
            lifecycle = str(row.get("lifecycle", "ACTIVE"))
            return_eligible = bool(row.get("return_eligible", True))
            unit_cost = float(row["unit_cost"])

            # Disposition condition: Obsolete/Phaseout OR Coverage > 52 weeks with excess > 10 units
            if (lifecycle in {"PHASE_OUT", "OBSOLETE"} and excess > 0) or (wos > 52.0 and excess >= 10):
                if return_eligible:
                    action = "VENDOR_RETURN"
                    econ_cat = "CASH_RECOVERED"
                    est_recovery = round(excess * unit_cost, 2)  # Full contract credit
                    notes = "Return to supplier under contractual return window."
                else:
                    action = "LIQUIDATE_OR_SCRAP"
                    econ_cat = "WORKING_CAPITAL_RELEASED"
                    est_recovery = round(excess * unit_cost * 0.25, 2)  # 25% salvage recovery
                    notes = "Not return eligible; liquidate through secondary channel or scrap to free pallet space."

                disposition_records.append({
                    "sku": row["sku"],
                    "dc": row["dc"],
                    "lifecycle_status": lifecycle,
                    "return_eligible": return_eligible,
                    "current_wos": wos,
                    "excess_units": int(excess),
                    "unit_cost": unit_cost,
                    "total_book_value": round(excess * unit_cost, 2),
                    "recommended_action": action,
                    "economic_category": econ_cat,
                    "estimated_cash_recovery": est_recovery,
                    "disposition_notes": notes,
                })

        df_disp = pd.DataFrame(disposition_records)
        if not df_disp.empty:
            df_disp = df_disp.sort_values(by="total_book_value", ascending=False).reset_index(drop=True)

        project_dir = FileIngestionService.get_project_dir(project_id)
        outputs_dir = project_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        disp_csv_path = outputs_dir / "disposition_action_queue.csv"
        df_disp.to_csv(disp_csv_path, index=False)

        # Register artifact
        art = Artifact(
            project_id=project_id,
            artifact_type="ACTION_QUEUE",
            file_path=str(disp_csv_path),
            summary="Excess Disposition Action Queue identifying Vendor Returns, Liquidations, and Scraps.",
        )
        db.add(art)
        await db.commit()

        total_disp_book_val = df_disp["total_book_value"].sum() if not df_disp.empty else 0.0
        total_cash_rec = df_disp["estimated_cash_recovery"].sum() if not df_disp.empty else 0.0

        return {
            "total_disposition_candidates": len(df_disp),
            "total_book_value_flagged": round(float(total_disp_book_val), 2),
            "total_estimated_cash_recovery": round(float(total_cash_rec), 2),
            "vendor_return_count": int((df_disp["recommended_action"] == "VENDOR_RETURN").sum()) if not df_disp.empty else 0,
            "liquidation_scrap_count": int((df_disp["recommended_action"] == "LIQUIDATE_OR_SCRAP").sum()) if not df_disp.empty else 0,
            "artifact_path": str(disp_csv_path),
            "top_disposition_candidates": df_disp.head(10).to_dict(orient="records") if not df_disp.empty else [],
        }
