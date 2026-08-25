import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Artifact, Project, ProjectFile
from app.tools.file_tools import FileIngestionService

logger = logging.getLogger(__name__)

# Try importing OR-Tools
try:
    from ortools.linear_solver import pywraplp
    OR_TOOLS_AVAILABLE = True
except ImportError:
    OR_TOOLS_AVAILABLE = False


class SupplyChainAnalyticsService:
    """
    Operations Research & Statistical Supply Chain Analytics Suite:
    1. ABC / XYZ / ADI / CV2 / Syntetos-Boylan demand intermittency classification.
    2. Dynamic Safety Stock (lead time & demand variance), Dynamic ROP, Order-Up-To (S), Target WOS.
    3. Exact Multi-DC Lateral Network Rebalancing MILP via Google OR-Tools.
    4. Lifecycle Disposition Queue (Contractual Vendor Returns vs Liquidation/Scrap).
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
        stmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == demand_file_id)
        res = await db.execute(stmt)
        demand_rec = res.scalar_one_or_none()
        if not demand_rec:
            return {"error": "Demand file not found in project."}

        df_demand = pd.read_csv(demand_rec.cleaned_path or demand_rec.raw_path)

        df_parts = pd.DataFrame()
        if parts_file_id:
            pstmt = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == parts_file_id)
            pres = await db.execute(pstmt)
            parts_rec = pres.scalar_one_or_none()
            if parts_rec:
                df_parts = pd.read_csv(parts_rec.cleaned_path or parts_rec.raw_path)

        sku_col = next((c for c in df_demand.columns if "part" in c.lower() or "sku" in c.lower()), df_demand.columns[0])
        qty_col = next((c for c in df_demand.columns if "qty" in c.lower() or "demand" in c.lower() or "sales" in c.lower()), df_demand.columns[-1])

        unit_costs: Dict[str, float] = {}
        if not df_parts.empty:
            p_sku_col = next((c for c in df_parts.columns if "part" in c.lower() or "sku" in c.lower()), df_parts.columns[0])
            cost_col = next((c for c in df_parts.columns if "cost" in c.lower() or "price" in c.lower()), None)
            if cost_col:
                unit_costs = dict(zip(df_parts[p_sku_col].astype(str), df_parts[cost_col].astype(float)))

        records = []
        for sku, group in df_demand.groupby(sku_col):
            sku_str = str(sku)
            series = group[qty_col].astype(float).values
            total_units = float(np.sum(series))
            unit_cost = unit_costs.get(sku_str, 50.0)
            total_dollars = total_units * unit_cost

            n_total = len(series)
            non_zeros = series[series > 0]
            n_nz = len(non_zeros)

            adi = (n_total / n_nz) if n_nz > 0 else 99.0
            mean_nz = float(np.mean(non_zeros)) if n_nz > 0 else 0.0
            std_nz = float(np.std(non_zeros, ddof=1)) if n_nz > 1 else 0.0
            cv2 = ((std_nz / mean_nz) ** 2) if mean_nz > 0 else 0.0

            if adi < 1.32 and cv2 < 0.49:
                sb_pattern = "Smooth"
            elif adi < 1.32 and cv2 >= 0.49:
                sb_pattern = "Erratic"
            elif adi >= 1.32 and cv2 < 0.49:
                sb_pattern = "Intermittent"
            else:
                sb_pattern = "Lumpy"

            overall_mean = float(np.mean(series)) if n_total > 0 else 0.0
            overall_std = float(np.std(series, ddof=1)) if n_total > 1 else 0.0
            cv_overall = (overall_std / overall_mean) if overall_mean > 0 else 99.0

            if cv_overall <= 0.5:
                xyz_class = "X"
            elif cv_overall <= 1.0:
                xyz_class = "Y"
            else:
                xyz_class = "Z"

            records.append({
                "sku": sku_str,
                "total_units": total_units,
                "unit_cost": unit_cost,
                "total_dollars": total_dollars,
                "mean_weekly_demand": overall_mean,
                "std_weekly_demand": overall_std,
                "adi": round(adi, 2),
                "cv2": round(cv2, 4),
                "demand_pattern": sb_pattern,
                "cv_overall": round(cv_overall, 2),
                "xyz_class": xyz_class,
            })

        df_res = pd.DataFrame(records)
        if df_res.empty:
            return {"error": "No valid SKU series found."}

        df_res = df_res.sort_values(by="total_dollars", ascending=False).reset_index(drop=True)
        tot_dollars = df_res["total_dollars"].sum()
        df_res["cum_dollar_pct"] = (df_res["total_dollars"].cumsum() / tot_dollars * 100) if tot_dollars > 0 else 0.0
        df_res["abc_dollar_class"] = df_res["cum_dollar_pct"].apply(
            lambda x: "A" if x <= 80.0 else ("B" if x <= 95.0 else "C")
        )

        df_res = df_res.sort_values(by="total_units", ascending=False).reset_index(drop=True)
        tot_units = df_res["total_units"].sum()
        df_res["cum_unit_pct"] = (df_res["total_units"].cumsum() / tot_units * 100) if tot_units > 0 else 0.0
        df_res["abc_unit_class"] = df_res["cum_unit_pct"].apply(
            lambda x: "A" if x <= 80.0 else ("B" if x <= 95.0 else "C")
        )

        project_dir = FileIngestionService.get_project_dir(project_id)
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        out_csv = analysis_dir / "sku_velocity_segmentation.csv"
        df_res.to_csv(out_csv, index=False)

        art = Artifact(
            project_id=project_id,
            artifact_type="ANALYSIS_TABLE",
            file_path=str(out_csv),
            summary=f"Velocity segmentation (ABC Dollar/Unit, XYZ, Syntetos-Boylan ADI/CV2) across {len(df_res)} SKUs.",
        )
        db.add(art)
        await db.commit()

        abc_dist = df_res["abc_dollar_class"].value_counts().to_dict()
        sb_dist = df_res["demand_pattern"].value_counts().to_dict()

        return {
            "project_id": project_id,
            "total_skus": len(df_res),
            "total_dollar_demand": round(float(tot_dollars), 2),
            "total_unit_demand": round(float(tot_units), 2),
            "abc_dollar_counts": abc_dist,
            "abc_dollar_distribution": abc_dist,
            "abc_unit_counts": df_res["abc_unit_class"].value_counts().to_dict(),
            "demand_pattern_counts": sb_dist,
            "demand_pattern_distribution": sb_dist,
            "xyz_counts": df_res["xyz_class"].value_counts().to_dict(),
            "file_path": str(out_csv),
            "artifact_path": str(out_csv),
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
        service_levels: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        sl_map = service_levels or {"A": 0.95, "B": 0.90, "C": 0.85}
        z_map = {"A": 1.645, "B": 1.282, "C": 1.036}

        inv_rec = (await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == inventory_file_id))).scalar_one_or_none()
        dem_rec = (await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == demand_file_id))).scalar_one_or_none()

        if not inv_rec or not dem_rec:
            return {"error": "Inventory or demand file not found in project."}

        df_inv = pd.read_csv(inv_rec.cleaned_path or inv_rec.raw_path)
        df_dem = pd.read_csv(dem_rec.cleaned_path or dem_rec.raw_path)

        df_parts = pd.DataFrame()
        if parts_file_id:
            p_rec = (await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == parts_file_id))).scalar_one_or_none()
            if p_rec:
                df_parts = pd.read_csv(p_rec.cleaned_path or p_rec.raw_path)

        inv_sku_col = next((c for c in df_inv.columns if "part" in c.lower() or "sku" in c.lower()), df_inv.columns[0])
        inv_dc_col = next((c for c in df_inv.columns if "wh" in c.lower() or "dc" in c.lower() or "warehouse" in c.lower() or "location" in c.lower()), df_inv.columns[1])
        oh_col = next((c for c in df_inv.columns if "hand" in c.lower() or "on_hand" in c.lower()), None)
        oo_col = next((c for c in df_inv.columns if "order" in c.lower() or "on_order" in c.lower()), None)

        dem_sku_col = next((c for c in df_dem.columns if "part" in c.lower() or "sku" in c.lower()), df_dem.columns[0])
        dem_dc_col = next((c for c in df_dem.columns if "wh" in c.lower() or "dc" in c.lower() or "warehouse" in c.lower() or "location" in c.lower()), None)
        qty_col = next((c for c in df_dem.columns if "qty" in c.lower() or "demand" in c.lower() or "sales" in c.lower()), df_dem.columns[-1])

        part_costs: Dict[str, float] = {}
        part_lead_times: Dict[str, float] = {}
        part_lt_stds: Dict[str, float] = {}
        part_abc: Dict[str, str] = {}

        if not df_parts.empty:
            p_col = next((c for c in df_parts.columns if "part" in c.lower() or "sku" in c.lower()), df_parts.columns[0])
            cost_c = next((c for c in df_parts.columns if "cost" in c.lower() or "price" in c.lower()), None)
            lt_c = next((c for c in df_parts.columns if "lead" in c.lower()), None)
            if cost_c:
                part_costs = dict(zip(df_parts[p_col].astype(str), df_parts[cost_c].astype(float)))
            if lt_c:
                part_lead_times = dict(zip(df_parts[p_col].astype(str), df_parts[lt_c].astype(float) / 7.0))

        project_dir = FileIngestionService.get_project_dir(project_id)
        analysis_dir = project_dir / "analysis"
        seg_file = analysis_dir / "sku_velocity_segmentation.csv"
        if seg_file.exists():
            df_seg = pd.read_csv(seg_file)
            part_abc = dict(zip(df_seg["sku"].astype(str), df_seg["abc_dollar_class"].astype(str)))

        results = []
        for _, row in df_inv.iterrows():
            sku = str(row[inv_sku_col])
            dc = str(row[inv_dc_col])
            oh = float(row[oh_col]) if oh_col else 0.0
            oo = float(row[oo_col]) if oo_col else 0.0

            if dem_dc_col and dem_dc_col in df_dem.columns:
                dem_slice = df_dem[(df_dem[dem_sku_col].astype(str) == sku) & (df_dem[dem_dc_col].astype(str) == dc)][qty_col].astype(float)
            else:
                dem_slice = df_dem[df_dem[dem_sku_col].astype(str) == sku][qty_col].astype(float)

            mean_d = float(dem_slice.mean()) if not dem_slice.empty else 1.0
            std_d = float(dem_slice.std()) if len(dem_slice) > 1 else (0.3 * mean_d)

            lt_weeks = part_lead_times.get(sku, 4.0)
            lt_std_weeks = part_lt_stds.get(sku, 0.5)
            review_period_weeks = 1.0

            abc_tier = part_abc.get(sku, "B")
            z_score = z_map.get(abc_tier, 1.282)
            unit_cost = part_costs.get(sku, 50.0)

            var_term = (lt_weeks * (std_d ** 2)) + ((mean_d ** 2) * (lt_std_weeks ** 2))
            ss_units = math.ceil(z_score * math.sqrt(max(0.1, var_term)))
            rop_units = math.ceil((mean_d * lt_weeks) + ss_units)
            s_order_up_to = math.ceil((mean_d * (lt_weeks + review_period_weeks)) + ss_units)
            target_wos = (s_order_up_to / mean_d) if mean_d > 0 else 0.0
            current_wos = (oh / mean_d) if mean_d > 0 else 0.0

            excess_units = max(0.0, oh - s_order_up_to)
            shortage_units = max(0.0, rop_units - (oh + oo))

            excess_dollars = excess_units * unit_cost
            shortage_dollars = shortage_units * unit_cost

            results.append({
                "sku": sku,
                "dc": dc,
                "abc_class": abc_tier,
                "unit_cost": unit_cost,
                "mean_weekly_demand": round(mean_d, 2),
                "std_weekly_demand": round(std_d, 2),
                "lead_time_weeks": round(lt_weeks, 2),
                "on_hand_units": oh,
                "on_order_units": oo,
                "safety_stock_units": ss_units,
                "rop_units": rop_units,
                "order_up_to_units": s_order_up_to,
                "current_wos": round(current_wos, 2),
                "target_wos": round(target_wos, 2),
                "excess_units": excess_units,
                "excess_dollars": round(excess_dollars, 2),
                "shortage_units": shortage_units,
                "shortage_dollars": round(shortage_dollars, 2),
                "on_hand_dollars": round(oh * unit_cost, 2),
            })

        df_policy = pd.DataFrame(results)
        policy_csv = analysis_dir / "stocking_policy_evaluation.csv"
        df_policy.to_csv(policy_csv, index=False)

        art = Artifact(
            project_id=project_id,
            artifact_type="ANALYSIS_TABLE",
            file_path=str(policy_csv),
            summary=f"Dynamic stocking policy evaluation across {len(df_policy)} SKU-DC nodes.",
        )
        db.add(art)
        await db.commit()

        tot_excess_val = float(df_policy["excess_dollars"].sum())
        tot_shortage_val = float(df_policy["shortage_dollars"].sum())
        tot_on_hand_val = float(df_policy["on_hand_dollars"].sum())

        overstocked_cnt = int((df_policy["excess_units"] > 0).sum())
        understocked_cnt = int((df_policy["shortage_units"] > 0).sum())

        return {
            "project_id": project_id,
            "total_nodes_evaluated": len(df_policy),
            "total_on_hand_dollars": round(tot_on_hand_val, 2),
            "total_excess_dollars": round(tot_excess_val, 2),
            "total_shortage_dollars": round(tot_shortage_val, 2),
            "overstocked_nodes_count": overstocked_cnt,
            "understocked_nodes_count": understocked_cnt,
            "stockout_risk_nodes_count": understocked_cnt,
            "nodes_in_excess": overstocked_cnt,
            "nodes_in_shortage": understocked_cnt,
            "file_path": str(policy_csv),
        }

    @classmethod
    async def generate_rebalance_candidates(
        cls,
        db: AsyncSession,
        project_id: str,
        transfer_lanes_file_id: Optional[str] = None,
        max_transfers: int = 50,
    ) -> Dict[str, Any]:
        project_dir = FileIngestionService.get_project_dir(project_id)
        analysis_dir = project_dir / "analysis"
        outputs_dir = project_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        policy_csv = analysis_dir / "stocking_policy_evaluation.csv"
        if not policy_csv.exists():
            return {"error": "Stocking policy evaluation not found. Run calculate_stocking_policy first."}

        df_policy = pd.read_csv(policy_csv)

        df_lanes = pd.DataFrame()
        if transfer_lanes_file_id:
            l_rec = (await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == transfer_lanes_file_id))).scalar_one_or_none()
            if l_rec:
                df_lanes = pd.read_csv(l_rec.cleaned_path or l_rec.raw_path)

        lane_costs: Dict[Tuple[str, str], float] = {}
        lane_transit: Dict[Tuple[str, str], float] = {}

        if not df_lanes.empty:
            orig_col = next((c for c in df_lanes.columns if "orig" in c.lower() or "from" in c.lower() or "src" in c.lower()), df_lanes.columns[0])
            dest_col = next((c for c in df_lanes.columns if "dest" in c.lower() or "to" in c.lower()), df_lanes.columns[1])
            cost_col = next((c for c in df_lanes.columns if "cost" in c.lower() or "rate" in c.lower()), None)
            days_col = next((c for c in df_lanes.columns if "transit" in c.lower() or "days" in c.lower()), None)

            for _, row in df_lanes.iterrows():
                o = str(row[orig_col])
                d = str(row[dest_col])
                c = float(row[cost_col]) if cost_col else 4.5
                t = float(row[days_col]) if days_col else 3.0
                lane_costs[(o, d)] = c
                lane_transit[(o, d)] = t

        source_nodes = df_policy[df_policy["excess_units"] > 0].copy()
        dest_nodes = df_policy[df_policy["shortage_units"] > 0].copy()

        if source_nodes.empty or dest_nodes.empty:
            return {"message": "No lateral rebalance candidates needed; no overlapping excess and shortage nodes."}

        rebalance_records = []
        solver_status_str = "HEURISTIC"

        if OR_TOOLS_AVAILABLE:
            try:
                solver = pywraplp.Solver.CreateSolver("SCIP") or pywraplp.Solver.CreateSolver("CBC")
                if solver:
                    x_vars = {}
                    cand_pairs = []

                    for s_idx, s_row in source_nodes.iterrows():
                        sku = s_row["sku"]
                        src_dc = s_row["dc"]
                        avail_excess = int(s_row["excess_units"])
                        unit_cost = float(s_row["unit_cost"])

                        for d_idx, d_row in dest_nodes.iterrows():
                            if d_row["sku"] != sku or d_row["dc"] == src_dc:
                                continue

                            dst_dc = d_row["dc"]
                            shortage_qty = int(d_row["shortage_units"])
                            lane_cost = lane_costs.get((src_dc, dst_dc), 4.5)
                            transit_days = lane_transit.get((src_dc, dst_dc), 3.0)

                            if transit_days >= 28.0:
                                continue

                            upper_bound = min(avail_excess, shortage_qty)
                            if upper_bound > 0:
                                var_name = f"x_{sku}_{src_dc}_{dst_dc}"
                                var = solver.IntVar(0, upper_bound, var_name)
                                x_vars[(s_idx, d_idx)] = var
                                cand_pairs.append((s_idx, d_idx, sku, src_dc, dst_dc, unit_cost, lane_cost, transit_days))

                    if x_vars:
                        for s_idx, s_row in source_nodes.iterrows():
                            out_vars = [x_vars[(s, d)] for (s, d) in x_vars if s == s_idx]
                            if out_vars:
                                solver.Add(solver.Sum(out_vars) <= int(s_row["excess_units"]))

                        for d_idx, d_row in dest_nodes.iterrows():
                            in_vars = [x_vars[(s, d)] for (s, d) in x_vars if d == d_idx]
                            if in_vars:
                                solver.Add(solver.Sum(in_vars) <= int(d_row["shortage_units"]))

                        objective = solver.Objective()
                        for (s_idx, d_idx, sku, src_dc, dst_dc, unit_cost, lane_cost, transit_days) in cand_pairs:
                            var = x_vars[(s_idx, d_idx)]
                            net_cost_coeff = lane_cost - (unit_cost * 1.5)
                            objective.SetCoefficient(var, net_cost_coeff)
                        objective.SetMinimization()

                        status = solver.Solve()
                        if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
                            solver_status_str = "OPTIMAL_OR_TOOLS_MILP"
                            for (s_idx, d_idx, sku, src_dc, dst_dc, unit_cost, lane_cost, transit_days) in cand_pairs:
                                qty = int(x_vars[(s_idx, d_idx)].solution_value())
                                if qty > 0:
                                    rebalance_records.append({
                                        "sku": sku,
                                        "origin_dc": src_dc,
                                        "destination_dc": dst_dc,
                                        "transfer_units": qty,
                                        "unit_cost": unit_cost,
                                        "rebalanced_asset_value": round(qty * unit_cost, 2),
                                        "freight_cost_per_unit": lane_cost,
                                        "estimated_freight_cost": round(qty * lane_cost, 2),
                                        "transit_days": transit_days,
                                        "supplier_lead_time_days": 28.0,
                                        "economic_category": "INVENTORY_REPOSITIONED",
                                        "reason": f"OR-Tools MILP optimal match relieving shortage in {dst_dc}.",
                                    })
            except Exception as e:
                logger.warning(f"OR-Tools MILP solver fallback: {e}")

        if not rebalance_records:
            solver_status_str = "HEURISTIC_PRIORITY"
            for _, d_row in dest_nodes.sort_values(by="shortage_dollars", ascending=False).iterrows():
                sku = d_row["sku"]
                dst_dc = d_row["dc"]
                shortage_qty = d_row["shortage_units"]
                unit_cost = d_row["unit_cost"]

                matching_sources = source_nodes[source_nodes["sku"] == sku].sort_values(by="excess_units", ascending=False)
                for _, s_row in matching_sources.iterrows():
                    src_dc = s_row["dc"]
                    if src_dc == dst_dc:
                        continue

                    avail_excess = source_nodes.loc[s_row.name, "excess_units"]
                    if avail_excess <= 0:
                        continue

                    transfer_qty = min(shortage_qty, avail_excess)
                    if transfer_qty <= 0:
                        continue

                    lane_cost = lane_costs.get((src_dc, dst_dc), 4.5)
                    transit_days = lane_transit.get((src_dc, dst_dc), 3.0)

                    rebalance_records.append({
                        "sku": sku,
                        "origin_dc": src_dc,
                        "destination_dc": dst_dc,
                        "transfer_units": int(transfer_qty),
                        "unit_cost": unit_cost,
                        "rebalanced_asset_value": round(transfer_qty * unit_cost, 2),
                        "freight_cost_per_unit": lane_cost,
                        "estimated_freight_cost": round(transfer_qty * lane_cost, 2),
                        "transit_days": transit_days,
                        "supplier_lead_time_days": 28.0,
                        "economic_category": "INVENTORY_REPOSITIONED",
                        "reason": f"Heuristic priority match relieving shortage in {dst_dc}.",
                    })

                    source_nodes.loc[s_row.name, "excess_units"] -= transfer_qty
                    shortage_qty -= transfer_qty
                    if shortage_qty <= 0:
                        break

        df_reb = pd.DataFrame(rebalance_records)
        out_csv = outputs_dir / "rebalance_action_queue.csv"
        df_reb.to_csv(out_csv, index=False)

        art = Artifact(
            project_id=project_id,
            artifact_type="ACTION_QUEUE",
            file_path=str(out_csv),
            summary=f"Multi-DC Lateral Rebalance Action Queue ({len(df_reb)} line-item transfers, Solver: {solver_status_str}).",
        )
        db.add(art)
        await db.commit()

        total_reb_val = float(df_reb["rebalanced_asset_value"].sum()) if not df_reb.empty else 0.0
        total_freight = float(df_reb["estimated_freight_cost"].sum()) if not df_reb.empty else 0.0

        return {
            "project_id": project_id,
            "total_transfers": len(df_reb),
            "total_rebalance_actions": len(df_reb),
            "top_transfers": rebalance_records[:10],
            "solver_engine": solver_status_str,
            "total_rebalanced_asset_value": round(total_reb_val, 2),
            "total_estimated_freight_cost": round(total_freight, 2),
            "economic_category": "INVENTORY_REPOSITIONED",
            "file_path": str(out_csv),
        }

    @classmethod
    async def generate_disposition_candidates(
        cls,
        db: AsyncSession,
        project_id: str,
    ) -> Dict[str, Any]:
        project_dir = FileIngestionService.get_project_dir(project_id)
        analysis_dir = project_dir / "analysis"
        outputs_dir = project_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        policy_csv = analysis_dir / "stocking_policy_evaluation.csv"
        if not policy_csv.exists():
            return {"error": "Stocking policy evaluation not found."}

        df_policy = pd.read_csv(policy_csv)
        excess_skus = df_policy[df_policy["excess_units"] > 0].copy()

        disp_records = []
        for _, row in excess_skus.iterrows():
            sku = str(row["sku"])
            dc = str(row["dc"])
            excess_units = float(row["excess_units"])
            unit_cost = float(row["unit_cost"])
            excess_dollars = float(row["excess_dollars"])
            abc_class = str(row.get("abc_class", "C"))

            if abc_class == "C":
                route = "VENDOR_RETURN"
                recovery_rate = 0.85
                rec_val = excess_dollars * recovery_rate
                category = "CASH_RECOVERED"
                action_text = f"File vendor return authorization for {excess_units:,.0f} units at 85% credit."
            else:
                route = "SECONDARY_LIQUIDATION"
                recovery_rate = 0.30
                rec_val = excess_dollars * recovery_rate
                category = "WORKING_CAPITAL_RELEASED"
                action_text = f"Liquidate {excess_units:,.0f} units to clear warehouse pallet capacity."

            disp_records.append({
                "sku": sku,
                "dc": dc,
                "excess_units": excess_units,
                "unit_cost": unit_cost,
                "total_book_value": excess_dollars,
                "disposition_route": route,
                "estimated_recovery_rate": recovery_rate,
                "estimated_cash_recovery": round(rec_val, 2),
                "economic_category": category,
                "action_recommendation": action_text,
            })

        df_disp = pd.DataFrame(disp_records)
        out_csv = outputs_dir / "disposition_action_queue.csv"
        df_disp.to_csv(out_csv, index=False)

        art = Artifact(
            project_id=project_id,
            artifact_type="ACTION_QUEUE",
            file_path=str(out_csv),
            summary=f"Lifecycle inventory disposition queue ({len(df_disp)} items).",
        )
        db.add(art)
        await db.commit()

        tot_book = float(df_disp["total_book_value"].sum()) if not df_disp.empty else 0.0
        tot_rec = float(df_disp["estimated_cash_recovery"].sum()) if not df_disp.empty else 0.0

        vendor_cnt = int((df_disp["disposition_route"] == "VENDOR_RETURN").sum()) if not df_disp.empty else 0
        scrap_cnt = int((df_disp["disposition_route"] != "VENDOR_RETURN").sum()) if not df_disp.empty else 0

        return {
            "project_id": project_id,
            "total_disposition_lines": len(df_disp),
            "total_disposition_candidates": len(df_disp),
            "total_excess_book_value": round(tot_book, 2),
            "total_estimated_cash_recovery": round(tot_rec, 2),
            "vendor_return_lines": vendor_cnt,
            "vendor_returns_count": vendor_cnt,
            "scrap_clearance_count": scrap_cnt,
            "liquidation_scrap_count": scrap_cnt,
            "file_path": str(out_csv),
        }
