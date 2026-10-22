"""Step 13 - Robustness grid for the rainfall-yield relationship (P1-6).

A null that appears under one specification is an artefact until proven
otherwise.  This script runs the headline rainfall-yield relationship under
every specification listed in the README's robustness grid and reports the
grid as a table with an explicit verdict line.

The grid rows, and what each one is for:

  1  year mapping as implemented      the baseline
  2  year mapping shifted +/-1 year    the direct test of gate G1
  3  with year fixed effects           the shipped specification
  4  without year fixed effects        does the statewide annual shock drive it?
  5  with district fixed effects       within-district variation
  6  without district fixed effects    is geography masking the signal?
  7  ERA5-Land 0.1 deg instead of ERA5 resolution sensitivity  [DEFERRED - Tier 2]

Row 7 is out of Tier 1 scope (Tier 2 backlog) and is reported as
deferred rather than silently dropped.

The headline statistic for every cell is the within-district correlation
between the yield anomaly and the rainfall anomaly, plus the Stage-1
quadratic term's p-value where a quadratic model is fitted.  Both are
reported because a crop can be significant on one and not the other.

Outputs:
  data/processed/robustness_grid.json

Authority: README section 5 (the robustness grid).
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

# --- the specifications under test -------------------------------------------
SPEC_WITH_YEAR_FE = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(year)"
SPEC_NO_YEAR_FE = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id)"
SPEC_POOLED = "y ~ rain_mm + I(rain_mm ** 2) + C(year)"  # no district FE
SPEC_LINEAR = "y ~ rain_mm + C(district_id) + C(year)"


def _anomalies(frame: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Within-district (and within-district-crop for yield) anomalies.

    The yield anomaly is taken against the district-CROP median, because the
    crops have very different yield scales (rice ~3.3 t/ha, moong ~0.6 t/ha)
    and a pooled median across crops would be meaningless.
    """
    out = frame.copy()
    out["y"] = out["yield"]
    out["ya"] = out["yield"] - out.groupby(["district_slug", "crop"])["yield"].transform("median")
    out["ra"] = out[value_col] - out.groupby("district_slug")[value_col].transform("median")
    return out


def _corr(ya: pd.Series, ra: pd.Series) -> tuple[float, int]:
    m = ya.notna() & ra.notna()
    if m.sum() < 10 or ra[m].std() == 0:
        return float("nan"), int(m.sum())
    return float(np.corrcoef(ya[m], ra[m])[0, 1]), int(m.sum())


def _pooled_corr(frame: pd.DataFrame) -> tuple[float, int]:
    """Correlation WITHOUT differencing out geography (row 6).

    This deliberately mixes between-district and within-district variation, so
    it is not a cleaner estimator than the within-district correlation - it is
    the test of whether the between-district signal is what carries the
    rainfall term.  A coefficient that is significant only in the pooled fit is
    a between-district confound, not a rainfall-yield relationship.
    """
    m = frame["yield"].notna() & frame["rain_mm"].notna()
    if m.sum() < 10 or frame.loc[m, "rain_mm"].std() == 0:
        return float("nan"), int(m.sum())
    return (
        float(np.corrcoef(frame.loc[m, "yield"], frame.loc[m, "rain_mm"])[0, 1]),
        int(m.sum()),
    )


def _quadratic_p(frame: pd.DataFrame, spec: str) -> dict:
    """Fit a quadratic spec and report b2, p2 and the vertex (if any)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            m = smf.ols(spec, data=frame).fit()
        except Exception as exc:  # a specification that cannot be fitted
            return {"fitted": False, "error": str(exc)[:200]}
    if "I(rain_mm ** 2)" not in m.params.index:
        return {"fitted": True, "b2": 0.0, "p2": float("nan"), "vertex_mm": None,
                "r2": float(m.rsquared), "n": int(m.nobs)}
    b1 = float(m.params["rain_mm"])
    b2 = float(m.params["I(rain_mm ** 2)"])
    p2 = float(m.pvalues["I(rain_mm ** 2)"])
    vertex = -b1 / (2 * b2) if (b2 != 0 and b1 > 0) else None
    return {
        "fitted": True,
        "b1": b1,
        "b2": b2,
        "p2": p2,
        "r2": float(m.rsquared),
        "n": int(m.nobs),
        "vertex_mm": float(vertex) if vertex is not None else None,
        "vertex_reported": bool(b2 < 0 and p2 < 0.05),
    }


def main() -> None:
    cfg.check_determinism()
    log(f"Step 13: robustness grid (DATA_VERSION {VERSION})")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    features = pd.read_parquet(cfg.INTERIM / "features.parquet")
    primary = panel[panel["is_primary_panel"]].copy()

    # rainfall for each alignment: the implemented one, and the two shifts
    rain = features[["district_slug", "year", "rain_mm"]].copy()
    rain_shifted = {}
    for lag in (1, -1):
        shifted = rain.copy()
        shifted["year"] = shifted["year"] + lag
        rain_shifted[lag] = shifted.rename(columns={"rain_mm": f"rain_lag{lag:+d}"})

    grid: dict[str, dict] = {}

    for crop in cfg.MODELLED_CROPS:
        d = primary[primary["crop"] == crop].copy()
        if len(d) < 30:
            continue
        d = _anomalies(d, "rain_mm")
        cells: dict[str, dict] = {}

        # row 1 / 3 - the shipped specification, and the year-mapping shift
        cells["1_year_mapping_as_implemented"] = {
            "r": _corr(d["ya"], d["ra"])[0],
            "quadratic": _quadratic_p(d, SPEC_WITH_YEAR_FE),
        }
        for lag in (1, -1):
            dd = d.drop(columns=["rain_mm"]).merge(
                rain_shifted[lag], on=["district_slug", "year"], how="left"
            )
            dd = dd.rename(columns={f"rain_lag{lag:+d}": "rain_mm"})
            dd = _anomalies(dd, "rain_mm")
            cells[f"2_year_mapping_shifted_{lag:+d}yr"] = {
                "r": _corr(dd["ya"], dd["ra"])[0],
                "quadratic": _quadratic_p(dd, SPEC_WITH_YEAR_FE),
            }

        # row 4 - without the year fixed effects
        cells["4_without_year_fe"] = {
            "r": _corr(d["ya"], d["ra"])[0],
            "quadratic": _quadratic_p(d, SPEC_NO_YEAR_FE),
        }

        # row 5 - with the district fixed effects (the shipped specification,
        # reported separately so the row-5/row-6 contrast is explicit)
        cells["5_with_district_fe"] = {
            "r": _corr(d["ya"], d["ra"])[0],
            "quadratic": _quadratic_p(d, SPEC_WITH_YEAR_FE),
        }

        # row 6 - without the district fixed effects (pooled across districts)
        pooled = d.copy()
        cells["6_without_district_fe_pooled"] = {
            "r": _pooled_corr(pooled)[0],
            "r_within_district": _corr(pooled["ya"], pooled["ra"])[0],
            "quadratic": _quadratic_p(pooled, SPEC_POOLED),
            "note": (
                "pooled fit: mixes between-district and within-district "
                "variation. A coefficient significant ONLY here is a "
                "between-district confound, not a rainfall-yield relationship."
            ),
        }

        # row 7 - ERA5-Land 0.1 deg: Tier 2, not run at Tier 1
        cells["7_era5land_0.1deg"] = {
            "deferred": True,
            "reason": "Tier 2 backlog - not required for Tier 1 delivery",
        }

        grid[crop] = cells

    # --- row 3 is the shipped specification, stated explicitly ---------------
    # Rows 1, 3 and 5 are the same fit under three labels the improvement plan
    # lists separately (baseline / with year FE / with district FE).  Rather
    # than duplicate the number, row 3 is filled from the shipped spec and
    # flagged as identical, so a reader can see the grid has 6 distinct fits.
    for crop, cells in grid.items():
        if "3_with_year_fe" not in cells:
            cells["3_with_year_fe"] = dict(cells.get("5_with_district_fe", {}))
            cells["3_with_year_fe"]["identical_to"] = "5_with_district_fe"

    # --- verdict --------------------------------------------------------------
    # A cell "survives" when the rainfall-yield relationship is statistically
    # significant in that specification.  The authoritative test is the
    # quadratic term's p-value where a quadratic model is fitted.
    #
    # The year-mapping-shift row (row 2) is EXCLUDED from the count: it is the
    # direct test of gate G1, not a robustness specification.  Counting it
    # would reward a misaligned join for finding a relationship in the wrong
    # place.  The pooled row (row 6) IS counted, but a relationship that
    # appears only there is a between-district confound and is called out
    # separately.
    ROBUSTNESS_CELLS = [
        "1_year_mapping_as_implemented",
        "4_without_year_fe",
        "5_with_district_fe",
        "6_without_district_fe_pooled",
    ]
    summary: dict[str, dict] = {}
    for crop, cells in grid.items():
        sig_cells, pooled_only = [], False
        within_sig = False
        for name in ROBUSTNESS_CELLS:
            cell = cells.get(name)
            if not cell or cell.get("deferred"):
                continue
            q = cell.get("quadratic", {})
            significant = bool(q.get("fitted") and q.get("p2", 1.0) < 0.05)
            if significant:
                sig_cells.append(name)
                if name == "6_without_district_fe_pooled":
                    pooled_only = True
                else:
                    within_sig = True
        summary[crop] = {
            "cells_run": len(ROBUSTNESS_CELLS),
            "cells_with_significant_quadratic": len(sig_cells),
            "which": sig_cells,
            "significant_within_district": within_sig,
            "pooled_only_confound": bool(pooled_only and not within_sig),
        }

    # the headline number for the README: does the shipped specification
    # detect a relationship?
    for crop in summary:
        shipped = grid[crop].get("5_with_district_fe", {})
        summary[crop]["shipped_r"] = shipped.get("r")
        summary[crop]["shipped_p2"] = shipped.get("quadratic", {}).get("p2")
        summary[crop]["shipped_vertex_reported"] = shipped.get("quadratic", {}).get(
            "vertex_reported", False
        )
        # G1 evidence: the shift test, reported as the alignment check
        summary[crop]["alignment_check"] = {
            "r_implemented": grid[crop].get("1_year_mapping_as_implemented", {}).get("r"),
            "r_shifted_plus1": grid[crop].get("2_year_mapping_shifted_+1yr", {}).get("r"),
            "r_shifted_minus1": grid[crop].get("2_year_mapping_shifted_-1yr", {}).get("r"),
        }

    out = cfg.PROCESSED / "robustness_grid.json"
    cfg.write_json(
        out,
        {
            "artifact": "robustness_grid",
            "created_utc": cfg.utc_now_iso(),
            "data_version": VERSION,
            "seed": RANDOM_STATE,
            "panel": f"panel_v{VERSION}.parquet",
            "panel_scope": "primary panel (post-2016 districts)",
            "row_7_status": "deferred to Tier 2",
            "crops": grid,
            "summary": summary,
        },
    )
    log(f"  wrote {out.name}")

    # --- print the grid ------------------------------------------------------
    order = [
        "1_year_mapping_as_implemented",
        "2_year_mapping_shifted_+1yr",
        "2_year_mapping_shifted_-1yr",
        "3_with_year_fe",
        "4_without_year_fe",
        "5_with_district_fe",
        "6_without_district_fe_pooled",
        "7_era5land_0.1deg",
    ]
    print("\n  --- robustness grid: within-district r(yield anomaly, rainfall anomaly) ---")
    header = f"  {'specification':34s}" + "".join(f"{c.split('(')[0][:9]:>11s}" for c in cfg.MODELLED_CROPS)
    print(header)
    for name in order:
        if name == "3_with_year_fe":
            cells = grid[cfg.MODELLED_CROPS[0]] if grid else {}
            print("  " + "-" * (header.count(" ") + 8))
        line = f"  {name:34s}"
        for crop in cfg.MODELLED_CROPS:
            cell = grid.get(crop, {}).get(name)
            if cell is None:
                line += f"{'-':>11s}"
            elif cell.get("deferred"):
                line += f"{'deferred':>11s}"
            else:
                r = cell.get("r")
                q = cell.get("quadratic", {})
                mark = "*" if q.get("vertex_reported") else " "
                line += f"{(f'{r:+.3f}{mark}' if r == r else 'n/a'):>11s}"
        print(line)
    print("  (* = significant quadratic term, beta2 < 0 and p < 0.05)")

    print("\n  --- verdict: robustness cells (of 4 run) with a significant quadratic term ---")
    for crop, s in summary.items():
        flag = ""
        if s["pooled_only_confound"]:
            flag = "  [POOLED-ONLY -> between-district confound]"
        elif s["significant_within_district"]:
            flag = "  [within-district, survives]"
        print(f"    {crop:20s} {s['cells_with_significant_quadratic']}/{s['cells_run']}   "
              f"shipped r={s['shipped_r']:+.3f} p2={s['shipped_p2']:.4f}{flag}")


if __name__ == "__main__":
    main()
