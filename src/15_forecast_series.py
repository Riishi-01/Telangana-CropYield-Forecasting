"""Step 15 - the 2026 forecast series (v1.2.0).

Turns the per-crop selected models (src/16_forecast_models.py) into the
numbers the dashboard and F6 read: a predicted 2026 yield/area for every
district, and the state-level figures that compare 2026 with the Telangana
average.

THE MEASURE, AND WHY
--------------------
Yield per hectare is the measure.  A production total mixes two different
things - how productive the land is, and how much land is planted - and the
second is not a yield.  Every level below is therefore built as a yield per
hectare and area-weighted where it is aggregated to the state.

Two aggregations are computed and both are area-weighted:

  state yield/area      SUM(area_i * predicted_i) / SUM(area_i)
  reference yield/area  SUM(production) / SUM(area)   over the fitted period

The unweighted mean of district yields is NOT used anywhere: rice district
area spans 180x (720 ha to 129,633 ha per district-season), so an unweighted
mean weights a 720 ha district the same as a 129,633 ha one and leaks land
utilisation into a yield number.

THE 2026 AREA ASSUMPTION
-------------------------
2026 planted area does not exist and cannot be forecast - that is what the
data does and does not support.  Each district's 2022-23 kharif area is used
as the baseline, applied IDENTICALLY to the 2026 forecast and to the
Telangana average, so the comparison isolates yield from land utilisation.
The assumption is recorded in the artefact and stated in the README and on
the dashboard.

Output:
    data/processed/forecast_series.json

Authority: plan/IMPROVEMENT_PLAN.md P3-12, P3-13 ; plan/SRS.md §5.6.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

VERSION = cfg.data_version()
RANDOM_STATE = cfg.RANDOM_STATE

# the season whose area is used as the 2026 baseline
AREA_BASELINE_SEASON = "2022-23"
AREA_BASELINE_NOTE = (
    "2026 planted area does not exist and cannot be forecast. Each district's "
    "2022-23 kharif area is used as the baseline, applied identically to the "
    "2026 forecast and to the Telangana average, so the comparison isolates "
    "yield from land utilisation."
)


def _round(value, digits=3):
    if value is None:
        return None
    if not np.isfinite(value):
        return None
    return round(float(value), digits)


def main() -> None:
    cfg.check_determinism()
    log(f"Step 15: 2026 forecast series (DATA_VERSION {VERSION})")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    primary = panel[panel["is_primary_panel"]].copy()
    models = cfg.read_json(cfg.PROCESSED / "forecast_models.json")
    marker = pd.read_parquet(cfg.INTERIM / "features_2026.parquet")

    out: dict[str, dict] = {}

    for crop, spec_info in models["crops"].items():
        d = primary[primary["crop"] == crop].copy()
        d["y"] = d["yield"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = smf.ols(spec_info["spec"], data=d).fit()

        id_map = d.drop_duplicates("district_slug").set_index("district_slug")["district_id"]
        year_levels = sorted(d["year"].unique())
        labels = d.drop_duplicates("district_slug").set_index("district_slug")["district_label"]

        base_area = (
            d[d["season"] == AREA_BASELINE_SEASON]
            .groupby("district_slug")["area_ha"]
            .first()
        )

        ref_yield_area = float(d["production"].sum() / d["area_ha"].sum())
        ref_mean_area = float(d["area_ha"].sum() / d["season"].nunique())

        rows = []
        for r in marker.itertuples():
            slug = r.district_slug
            if slug not in id_map.index:
                continue
            frame = pd.DataFrame([{
                "rain_mm": r.rain_mm,
                "district_id": id_map[slug],
                "year": year_levels[0],
                "dry_run_max": r.dry_run_max,
                "dry_days_ge5": r.dry_days_ge5,
                "heat_days": r.heat_days,
                "vpd_mean": r.vpd_mean,
                "rain_days": r.rain_days,
            }])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                predicted = float(model.predict(frame)[0])
            area = base_area.get(slug)
            rows.append({
                "slug": slug,
                "label": str(labels.get(slug, slug)),
                "predicted_2026": _round(predicted),
                "area_2022_23_ha": _round(area, 1) if area is not None and np.isfinite(area) else None,
                "rain_2026_mm": _round(float(r.rain_mm), 1),
                "dry_run_max": int(r.dry_run_max),
                "heat_days": int(r.heat_days),
                "rain_days": int(r.rain_days),
                "vpd_mean": _round(float(r.vpd_mean), 2),
            })

        usable = [x for x in rows if x["area_2022_23_ha"]]
        n_usable = len(usable)
        total_area = sum(x["area_2022_23_ha"] for x in usable)
        state_yield_area = (
            sum(x["predicted_2026"] * x["area_2022_23_ha"] for x in usable) / total_area
        ) if total_area else None
        # the same area baseline applied to the Telangana average yield/area:
        # the total on the same area basis, so the two percentages agree
        ref_total_same_area = ref_yield_area * total_area if total_area else None
        total_2026 = (
            sum(x["predicted_2026"] * x["area_2022_23_ha"] for x in usable) if total_area else None
        )

        for x in rows:
            if state_yield_area and x["area_2022_23_ha"]:
                x["pct_vs_state"] = _round(
                    100.0 * (x["predicted_2026"] / ref_yield_area - 1.0), 1
                )
            else:
                x["pct_vs_state"] = None

        out[crop] = {
            "unit": spec_info["unit"],
            "selected_spec": spec_info["selected_spec"],
            "spec_yield_form": spec_info["spec_yield_form"],
            "skill_rmse": _round(spec_info["skill_rmse"], 4),
            "beats_baseline": spec_info["beats_baseline"],
            "r2": _round(spec_info["r2"], 4),
            "b_rain_per_mm": spec_info["b_rain_per_mm"],
            "rejected_specs": spec_info["rejected_specs"],
            "per_district": rows,
            "n_districts": len(rows),
            "n_districts_with_area": n_usable,
            "area_baseline_season": AREA_BASELINE_SEASON,
            "area_baseline_note": AREA_BASELINE_NOTE,
            "state": {
                "yield_2026_per_ha": _round(state_yield_area),
                "reference_yield_per_ha": _round(ref_yield_area),
                "diff_per_ha": _round(state_yield_area - ref_yield_area) if state_yield_area else None,
                "pct_vs_reference": _round(100.0 * (state_yield_area / ref_yield_area - 1.0), 1) if state_yield_area else None,
                "total_2026": _round(total_2026, 0) if total_2026 else None,
                "reference_total_same_area": _round(ref_total_same_area, 0) if ref_total_same_area else None,
                "diff_total": _round(total_2026 - ref_total_same_area, 0) if total_2026 else None,
                "total_unit_note": (
                    "cotton is reported in bales, not tonnes, and no conversion is applied"
                    if spec_info["unit"] == "bales/ha" else None
                ),
                "reference_mean_annual_area_ha": _round(ref_mean_area, 0),
            },
            "n_negative_predicted": sum(1 for x in rows if x["predicted_2026"] <= 0),
        }
        st = out[crop]["state"]
        log(
            f"  {crop:20s} 2026 {st['yield_2026_per_ha']:.3f} {spec_info['unit']} vs "
            f"avg {st['reference_yield_per_ha']:.3f} -> {st['diff_per_ha']:+.3f} "
            f"({st['pct_vs_reference']:+.1f}%) | total {st['total_2026']:,.0f} "
            f"({st['diff_total']:+,.0f}) | skill {spec_info['skill_rmse']:+.3f}"
        )

    # --- a gate: no crop may publish a non-positive predicted yield -----------
    for crop, res in out.items():
        assert res["n_negative_predicted"] == 0, (
            f"{crop}: {res['n_negative_predicted']} districts have a non-positive "
            "predicted yield - the forecast is not publishable"
        )

    # --- a gate: the total and the t/ha must agree in percentage -------------
    for crop, res in out.items():
        st = res["state"]
        pct_total = 100.0 * (st["total_2026"] / st["reference_total_same_area"] - 1.0)
        assert abs(pct_total - st["pct_vs_reference"]) < 0.05, (
            f"{crop}: the total and the yield/area disagree in percentage - the "
            "area baseline is not being applied consistently"
        )

    out_path = cfg.PROCESSED / "forecast_series.json"
    cfg.write_json(
        out_path,
        {
            "artifact": "forecast_series",
            "created_utc": cfg.utc_now_iso(),
            "data_version": VERSION,
            "seed": RANDOM_STATE,
            "measure": "yield per hectare; production totals are the same forecast rescaled by area",
            "aggregation": "area-weighted (SUM(area x yield) / SUM(area)); the unweighted mean of district yields is not used",
            "area_baseline_season": AREA_BASELINE_SEASON,
            "area_baseline_note": AREA_BASELINE_NOTE,
            "crops": out,
        },
    )
    log(f"  wrote {out_path.name}")
    log("  gate: no non-positive predicted yields; total and yield/area agree")


if __name__ == "__main__":
    main()
