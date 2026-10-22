"""Step 07 - Stage 2: augmented model with dry-spell, heat and VPD features.

Stage 2 adds to the Stage 1 specification (SRS §5.4):

    + dry_run_max + dry_days_ge5 + heat_days + vpd_mean + rain_days

The reported quantity is  dR2 = R2(Stage 2) - R2(Stage 1)  per crop, which is
the test of Bal et al. (2022)'s central claim on open data for Telangana: a
dry-spell index explains yield better than cumulative seasonal rainfall.

  dR2 materially positive -> dry-spell duration adds explanatory power beyond
                             cumulative rainfall.  This is the headline finding.
  dR2 ~ 0                   -> cumulative rainfall is sufficient for these
                             crops.  This is ALSO the headline finding.

Both outcomes are valid deliverables.  Neither is suppressed or reframed
(GUIDE §8).  An F-test on the added block is reported alongside dR2 because the
two models differ by five parameters.

Authority: plan/SRS.md §5.4 ; plan/GUIDE.md Step 8.
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

SPEC_STAGE1 = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(season)"
SPEC_STAGE2 = (
    "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(season) "
    "+ dry_run_max + dry_days_ge5 + heat_days + vpd_mean + rain_days"
)
STAGE2_EXTRA = ["dry_run_max", "dry_days_ge5", "heat_days", "vpd_mean", "rain_days"]


def fit(model_spec: str, data: pd.DataFrame):
    work = data.copy()
    work["y"] = work["yield"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return smf.ols(model_spec, data=work).fit()


def main() -> None:
    cfg.check_determinism()
    log("Step 07: Stage 2 augmented model")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    primary = panel[panel["is_primary_panel"]].copy()

    summary = cfg.read_json(cfg.PROCESSED / "model_summary.json")
    stage1 = summary["crops"]

    stage2: dict[str, dict] = {}

    for crop in cfg.MODELLED_CROPS:
        d = primary[primary["crop"] == crop].copy()
        if len(d) < 30 or crop not in stage1:
            continue

        m1 = fit(SPEC_STAGE1, d)
        m2 = fit(SPEC_STAGE2, d)

        r2_1, r2_2 = float(m1.rsquared), float(m2.rsquared)
        adj1, adj2 = float(m1.rsquared_adj), float(m2.rsquared_adj)
        d_r2 = r2_2 - r2_1
        d_adj_r2 = adj2 - adj1

        # partial F-test for the five added features
        q = len(STAGE2_EXTRA)
        n = float(m2.nobs)
        p_full = int(m2.df_model) + 1
        if 1.0 - r2_2 > 0:
            f_stat = ((r2_2 - r2_1) / q) / ((1.0 - r2_2) / (n - p_full))
        else:
            f_stat = float("nan")
        from scipy import stats  # local import: only needed here

        f_p = float(stats.f.sf(f_stat, q, n - p_full)) if np.isfinite(f_stat) else float("nan")

        extra_coefs = {
            name: {
                "coef": float(m2.params[name]),
                "p": float(m2.pvalues[name]),
                "std_err": float(m2.bse[name]),
            }
            for name in STAGE2_EXTRA
            if name in m2.params.index
        }

        # Vertex for the Stage 2 fit, under the same rule as Stage 1:
        # reported only when b2 < 0 and p(b2) < 0.05.
        vertex = vertex_ci = None
        has_vertex = False
        reason = None
        b2 = float(m2.params["I(rain_mm ** 2)"])
        p2 = float(m2.pvalues["I(rain_mm ** 2)"])
        b1 = float(m2.params["rain_mm"])
        if abs(b2) > 1e-12:
            vertex = -b1 / (2.0 * b2)
            d_b1 = -1.0 / (2.0 * b2)
            d_b2 = b1 / (2.0 * b2**2)
            cov = m2.cov_params()
            var = (
                d_b1**2 * cov.loc["rain_mm", "rain_mm"]
                + d_b2**2 * cov.loc["I(rain_mm ** 2)", "I(rain_mm ** 2)"]
                + 2.0 * d_b1 * d_b2 * cov.loc["rain_mm", "I(rain_mm ** 2)"]
            )
            se = float(np.sqrt(max(var, 0.0)))
            vertex_ci = [vertex - 1.959963985 * se, vertex + 1.959963985 * se]
            has_vertex = bool(b2 < 0 and p2 < 0.05)
            if not has_vertex:
                reason = (
                    "quadratic term is positive - relationship is convex, no inverted-U"
                    if b2 >= 0
                    else f"quadratic term is not significant at p<0.05 (p={p2:.3f})"
                )

        stage2[crop] = {
            "formula": SPEC_STAGE2.replace("y ~", "yield ~", 1),
            "n_rows": int(m2.nobs),
            "r2_stage1": r2_1,
            "r2_stage2": r2_2,
            "delta_r2": d_r2,
            "adj_r2_stage1": adj1,
            "adj_r2_stage2": adj2,
            "delta_adj_r2": d_adj_r2,
            "partial_f": f_stat,
            "partial_f_p": f_p,
            "added_features": extra_coefs,
            "rmse_stage1": float(np.sqrt(np.mean(m1.resid**2))),
            "rmse_stage2": float(np.sqrt(np.mean(m2.resid**2))),
            "b1": b1,
            "b2": b2,
            "p1": float(m2.pvalues["rain_mm"]),
            "p2": p2,
            "vertex_mm": vertex if has_vertex else None,
            "vertex_ci95_mm": vertex_ci if has_vertex else None,
            "vertex_reported": has_vertex,
            "vertex_reason": reason,
            "mean_fitted": float(np.mean(m2.fittedvalues)),
            "rain_mean_mm": float(d["rain_mm"].mean()),
            "rain_sq_mean": float((d["rain_mm"] ** 2).mean()),
            "rain_min_mm": float(d["rain_mm"].min()),
            "rain_max_mm": float(d["rain_mm"].max()),
            "unit": str(d["yield_unit"].iloc[0]),
        }

        if d_adj_r2 > 0.005 and f_p < 0.05:
            verdict = (
                "dry-spell/heat features ADD explanatory power beyond cumulative "
                "rainfall (significant on both dAdjR2 and the partial F-test)"
            )
        elif f_p < 0.05 or d_adj_r2 > 0.005:
            verdict = (
                "small increase in explained variance, not robust once the five "
                "extra parameters are accounted for"
            )
        else:
            verdict = (
                "cumulative rainfall is sufficient - the added features add no "
                "material explanatory power"
            )
        log(
            f"  {crop:20s} R2 {r2_1:.3f} -> {r2_2:.3f}   dR2 = {d_r2:+.4f} "
            f"(dAdjR2 {d_adj_r2:+.4f}, partial F p={f_p:.3f})  {verdict}"
        )

    summary["stage2"] = stage2
    summary["stage2_created_utc"] = cfg.utc_now_iso()
    summary["stage2_note"] = (
        "delta R2 = R2(Stage 2) - R2(Stage 1) on the primary panel; reported "
        "for every modelled crop regardless of sign or magnitude"
    )
    cfg.write_json(cfg.PROCESSED / "model_summary.json", summary)
    log("  wrote data/processed/model_summary.json (stage2 block)")

    # --- gate G8: dR2 reported for every modelled crop ----------------------
    for crop in cfg.MODELLED_CROPS:
        if crop in stage1:
            assert crop in stage2, f"{crop}: stage 2 missing"
            assert "delta_r2" in stage2[crop]
    log("  gate G8: dR2 reported for every modelled crop")


if __name__ == "__main__":
    main()
