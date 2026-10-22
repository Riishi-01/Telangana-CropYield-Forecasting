"""Step 06 - Stage 1: district + year fixed-effects quadratic response curve.

Specification:

    yield ~ rain_mm + I(rain_mm**2) + C(district_id) + C(year)

Estimator: OLS (statsmodels).  Vertex (optimum rainfall):

    R* = -b1 / (2 * b2)

A vertex is reported ONLY when b2 < 0 AND b2 is significant at p < 0.05.  If
that condition fails the relationship is monotonic or flat; that is reported
as a result and is never reframed as a vertex.

Robustness: every crop is refitted
  (a) without the year fixed effects, and
  (b) on the extended panel (era-tagged district ids, 2014-15 .. 2022-23).
All specifications are reported, including the ones that look worse.

Authority: README section 5 (Stage 1) and section 7 (limitations).
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
# OLS is deterministic and takes no random_state argument; the seed is
# recorded in the manifest and PYTHONHASHSEED is pinned by the runner.
RANDOM_STATE = cfg.RANDOM_STATE

SPEC_PRIMARY = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(year)"
SPEC_NO_YEAR_FE = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id)"
SPEC_LINEAR = "y ~ rain_mm + C(district_id) + C(year)"
SPEC_STAGE2 = (
    "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(year) "
    "+ dry_run_max + dry_days_ge5 + heat_days + vpd_mean + rain_days"
)


def fit_quadratic(data: pd.DataFrame, spec: str) -> dict:
    """Fit one OLS model and return everything the report needs."""
    # `yield` is a Python keyword and cannot be used as a patsy target, so the
    # response is copied to `y` (y == yield, unchanged).
    work = data.copy()
    work["y"] = work["yield"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = smf.ols(spec, data=work).fit()

    quadratic = "I(rain_mm ** 2)" in model.params.index
    b1 = float(model.params["rain_mm"])
    b2 = float(model.params["I(rain_mm ** 2)"]) if quadratic else 0.0
    p1 = float(model.pvalues["rain_mm"])
    p2 = float(model.pvalues["I(rain_mm ** 2)"]) if quadratic else float("nan")

    # delta-method standard error for the vertex R* = -b1 / (2 b2)
    vertex = None
    vertex_ci = None
    vertex_se = None
    if abs(b2) > 1e-12:
        vertex = -b1 / (2.0 * b2)
        d_b1 = -1.0 / (2.0 * b2)
        d_b2 = b1 / (2.0 * b2**2)
        cov = model.cov_params()
        var = (
            d_b1**2 * cov.loc["rain_mm", "rain_mm"]
            + d_b2**2 * cov.loc["I(rain_mm ** 2)", "I(rain_mm ** 2)"]
            + 2.0
            * d_b1
            * d_b2
            * cov.loc["rain_mm", "I(rain_mm ** 2)"]
        )
        vertex_se = float(np.sqrt(max(var, 0.0)))
        z = 1.959963985
        vertex_ci = [vertex - z * vertex_se, vertex + z * vertex_se]

    has_vertex = bool(b2 < 0 and p2 < 0.05)
    if has_vertex:
        reason = None
    elif b2 >= 0:
        reason = "quadratic term is positive - relationship is convex, no inverted-U"
    else:
        reason = f"quadratic term is not significant at p<0.05 (p={p2:.3f})"

    # limb slopes at the 25th and 75th percentile of observed rainfall
    r25 = float(data["rain_mm"].quantile(0.25))
    r75 = float(data["rain_mm"].quantile(0.75))
    rmin = float(data["rain_mm"].min())
    rmax = float(data["rain_mm"].max())
    slope_deficit = b1 + 2.0 * b2 * r25   # dY/dR at the dry end
    slope_excess = b1 + 2.0 * b2 * r75    # dY/dR at the wet end

    # Is the vertex inside the observed rainfall range, and is the curve still
    # rising over most of that range?  A vertex far beyond the data is an
    # extrapolation of the curvature, not an observed optimum.
    frac_below = None
    within = None
    monotonic_over_data = None
    frac_below = None
    n_above_vertex = None
    n_distinct_ds_above = None
    if has_vertex and vertex is not None:
        within = bool(rmin <= vertex <= rmax)
        frac_below = float((data["rain_mm"] < vertex).mean())
        monotonic_over_data = bool(slope_excess > 0 and slope_deficit > 0)
        # Tail support: how much data actually sits beyond the vertex?  A
        # vertex is only as well determined as the observations that constrain
        # the excess limb, so this count is reported alongside it.  It is
        # counted on district-seasons (a district-season is one observation
        # of the rainfall field) and on the full panel rows.
        above = data["rain_mm"] > vertex
        n_above_vertex = int(above.sum())
        n_distinct_ds_above = int(
            data.loc[above, ["district_id", "season"]].drop_duplicates().shape[0]
        )

    return {
        "formula": spec.replace("y ~", "yield ~", 1),
        "n_rows": int(model.nobs),
        "n_district_seasons": int(data[["district_id", "season"]].drop_duplicates().shape[0]),
        "n_districts": int(data["district_id"].nunique()),
        "n_seasons": int(data["season"].nunique()),
        "b1": b1,
        "b2": b2,
        "p1": p1,
        "p2": p2,
        "r2": float(model.rsquared),
        "adj_r2": float(model.rsquared_adj),
        "rmse": float(np.sqrt(np.mean(model.resid**2))),
        "intercept": float(model.params["Intercept"]),
        "vertex_mm": vertex if has_vertex else None,
        "vertex_se": vertex_se if has_vertex else None,
        "vertex_ci95_mm": vertex_ci if has_vertex else None,
        "vertex_reported": has_vertex,
        "vertex_reason": reason,
        "vertex_within_observed_range": within,
        "vertex_frac_obs_below": frac_below,
        "vertex_n_rows_above": n_above_vertex,
        "vertex_n_district_seasons_above": n_distinct_ds_above,
        "vertex_tail_support_note": (
            f"{n_distinct_ds_above} of "
            f"{int(data[['district_id', 'season']].drop_duplicates().shape[0])} "
            "district-seasons carry rainfall above the vertex, so the excess "
            "limb is estimated from a thin tail of the observed distribution."
            if has_vertex and vertex is not None else None
        ),
        "curve_rising_over_most_of_range": monotonic_over_data,
        "mean_fitted": float(np.mean(model.fittedvalues)),
        "rain_mean_mm": float(data["rain_mm"].mean()),
        "rain_sq_mean": float((data["rain_mm"] ** 2).mean()),
        "rain_min_mm": rmin,
        "rain_max_mm": rmax,
        "rain_p25_mm": r25,
        "rain_p75_mm": r75,
        "slope_deficit_limb": slope_deficit,
        "slope_excess_limb": slope_excess,
        "unit": str(data["yield_unit"].iloc[0]),
    }


def main() -> None:
    cfg.check_determinism()
    log("Step 06: Stage 1 response curve")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    primary = panel[panel["is_primary_panel"]].copy()
    extended = panel.copy()

    results: dict[str, dict] = {}

    for crop in cfg.MODELLED_CROPS:
        d_prim = primary[primary["crop"] == crop].copy()
        d_ext = extended[extended["crop"] == crop].copy()
        if len(d_prim) < 30:
            log(f"  {crop}: only {len(d_prim)} rows - skipping")
            continue

        res = {
            "primary": fit_quadratic(d_prim, SPEC_PRIMARY),
            "no_year_fe": fit_quadratic(d_prim, SPEC_NO_YEAR_FE),
            "linear_only": fit_quadratic(d_prim, SPEC_LINEAR),
            "extended_panel": fit_quadratic(d_ext, SPEC_PRIMARY),
        }
        results[crop] = res

        p = res["primary"]
        log(
            f"  {crop:20s} n={p['n_rows']:3d}  b1={p['b1']:+.6f}  b2={p['b2']:+.3e}  "
            f"p2={p['p2']:.4f}  R2={p['r2']:.3f}"
        )
        if p["vertex_reported"]:
            lo, hi = p["vertex_ci95_mm"]
            log(
                f"    vertex R* = {p['vertex_mm']:.1f} mm "
                f"(95% CI {lo:.1f} to {hi:.1f})  "
                f"deficit limb {p['slope_deficit_limb']:+.5f} /ha per mm  "
                f"excess limb {p['slope_excess_limb']:+.5f}"
            )
        else:
            log(f"    NO VERTEX REPORTED: {p['vertex_reason']}")
        ny = res["no_year_fe"]
        ex = res["extended_panel"]
        lin = res["linear_only"]
        log(
            f"    linear-only: b1={lin['b1']:+.6f} p={lin['p1']:.4f} "
            f"(rainfall effect is "
            f"{'positive and significant' if lin['b1'] > 0 and lin['p1'] < 0.05 else 'not significant at p<0.05'})"
        )
        log(
            f"    robustness: no year FE -> vertex "
            f"{ny['vertex_mm'] if ny['vertex_reported'] else 'n/a'}"
            f" | extended panel -> vertex "
            f"{ex['vertex_mm'] if ex['vertex_reported'] else 'n/a'}"
        )
        if p["vertex_reported"]:
            log(
                f"    vertex sits at {p['vertex_frac_obs_below']*100:.0f}% of observed "
                f"rainfall; within observed range: {p['vertex_within_observed_range']}; "
                f"curve still rising over most of the range: "
                f"{p['curve_rising_over_most_of_range']}"
            )
            log(
                f"    tail support: {p['vertex_n_district_seasons_above']} of "
                f"{p['n_district_seasons']} district-seasons carry rainfall above "
                f"the vertex (observed rainfall range {p['rain_min_mm']:.0f}-"
                f"{p['rain_max_mm']:.0f} mm)"
            )

    out = cfg.PROCESSED / "model_summary.json"
    fitted_seasons = sorted(primary["season"].unique())
    fitted_years = sorted(int(y) for y in primary["year"].unique())
    payload = {
        "created_utc": cfg.utc_now_iso(),
        "data_version": VERSION,
        "stage": "stage1",
        "estimator": "OLS (statsmodels)",
        "spec_primary": SPEC_PRIMARY,
        "spec_no_year_fe": SPEC_NO_YEAR_FE,
        "vertex_rule": "reported only when b2 < 0 and p(b2) < 0.05",
        "fitted_range": {
            "panel": "primary panel (post-2016 districts)",
            "seasons": fitted_seasons,
            "years": fitted_years,
            "n_seasons": len(fitted_seasons),
            "n_rows": int(len(primary)),
            "n_districts": int(primary["district_id"].nunique()),
        },
        "dataset_range": {
            "seasons": sorted(panel["season"].unique()),
            "n_rows": int(len(panel)),
            "note": (
                "the dataset covers 2014-15 -> 2022-23; the models are fitted "
                "on the primary panel and the earlier seasons appear only in "
                "the extended-panel robustness specification"
            ),
        },
        "year_mapping": cfg.YEAR_MAPPING,
        "year_mapping_source": cfg.YEAR_MAPPING_SOURCE,
        "crops": results,
    }
    cfg.write_json(out, payload)
    log(f"  wrote {out}")
    log(f"  fitted range: {fitted_seasons[0]} -> {fitted_seasons[-1]} "
        f"({len(fitted_seasons)} seasons, {len(primary)} rows)")

    # --- gate G7.3: both specifications present for every crop --------------
    for crop, res in results.items():
        assert "primary" in res and "no_year_fe" in res and "extended_panel" in res, (
            f"{crop}: missing a robustness specification"
        )
    log("  gate G7.3: both FE specifications reported for every crop")


if __name__ == "__main__":
    main()
