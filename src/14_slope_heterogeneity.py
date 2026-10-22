"""Step 14 - District-level slope heterogeneity test (P1-9).

The shipped Stage 1 model assumes ONE shared rainfall slope across all 32
districts.  The defence so far has been that a per-district slope would be
fitted on 7 points, which is too few.  That defence is correct for a set of
32 unconnected regressions, but it is not the end of the question: partial
pooling (a mixed-effects model with random slopes) is exactly the method
designed for sparse groups, because it shrinks each district's slope toward
the global slope instead of leaving it unestimated.

This script fits, per crop:

    MixedLM(yield ~ rain_mm, groups=district_id, re_formula="~rain_mm")

and reports a likelihood-ratio test of

    H0: all district rainfall slopes are equal (the random-slope variance is 0)

against the random-intercept-only model.  The LRT p-value turns "we could not
estimate it" into "we tested it and here is the answer" (P1-9).

Three models are fitted per crop:

  1. random intercept only        - the shipped assumption (one shared slope)
  2. random intercept + slope     - partial pooling of district slopes
  3. the shipped OLS              - the reference, for R2 comparison

The test is the LRT of (2) against (1): a significant p-value means district
rainfall sensitivities genuinely differ and the shared-slope assumption is
wrong for that crop.

Outputs:
  data/processed/slope_heterogeneity.json

Authority: README section 5 (mixed-effects test).
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.regression.mixed_linear_model import MixedLM

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

VERSION = cfg.data_version()
RANDOM_STATE = cfg.RANDOM_STATE

SPEC_OLS = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(year)"


def _fit_mixed(frame: pd.DataFrame, random_slope: bool):
    """Fit a MixedLM, returning (result, error_or_None).

    The optimiser matters.  The random-slope model has a poorly identified
    variance component, and the default L-BFGS lands in a local optimum
    whose log-likelihood is BELOW the random-intercept model's - which shows
    up as a negative likelihood-ratio statistic, i.e. an artefact of the
    optimiser rather than a finding.  Powell is the only tested optimiser that
    reliably finds the optimum for the random-slope fit, so it is tried first
    and the rest are fallbacks.  The best (highest) log-likelihood wins.
    """
    re_formula = "~rain_mm" if random_slope else "~1"
    best, best_err = None, None
    for method in ("powell", "lbfgs", "nm"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                model = MixedLM.from_formula(
                    "y ~ rain_mm", frame, groups=frame["district_id"],
                    re_formula=re_formula,
                )
                res = model.fit(reml=False, method=method)
            except Exception as exc:
                if best_err is None:
                    best_err = f"{type(exc).__name__}: {exc}"[:200]
                continue
        if best is None or res.llf > best.llf:
            best = res
    if best is None:
        return None, best_err
    return best, None


def main() -> None:
    cfg.check_determinism()
    log(f"Step 14: district slope heterogeneity test (DATA_VERSION {VERSION})")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    primary = panel[panel["is_primary_panel"]].copy()

    results: dict[str, dict] = {}

    for crop in cfg.MODELLED_CROPS:
        d = primary[primary["crop"] == crop].copy().reset_index(drop=True)
        if len(d) < 60:
            continue
        d["y"] = d["yield"]

        ri, err_ri = _fit_mixed(d, random_slope=False)
        rs, err_rs = _fit_mixed(d, random_slope=True)
        if ri is None or rs is None:
            log(f"  {crop}: mixed model failed (ri={err_ri}) (rs={err_rs})")
            results[crop] = {"fitted": False, "error_ri": err_ri, "error_rs": err_rs}
            continue

        # --- likelihood-ratio test of H0: random-slope variance = 0 ----------
        lrt = 2.0 * (rs.llf - ri.llf)
        from scipy import stats as st

        # A negative LRT means the random-slope model fitted WORSE than the
        # random-intercept model, which is a boundary/optimisation artefact,
        # not evidence for H0.  Report it as such and treat it as a
        # non-significant result rather than a spurious p-value of 1.
        lrt_valid = lrt > 0
        p_lrt = float(st.chi2.sf(max(lrt, 0.0), 1)) if lrt_valid else float("nan")
        significant = bool(lrt_valid and p_lrt < 0.05)

        # --- the shrunken per-district slopes --------------------------------
        re_slopes = {}
        try:
            for i, name in enumerate(rs.model.exog_names):
                pass
            rand = rs.random_effects
            for district, re in rand.items():
                # re is a Series indexed by the random-effects terms
                vals = list(np.atleast_1d(np.asarray(re, dtype=float)))
                if len(vals) >= 2:
                    re_slopes[str(district)] = float(vals[1])
        except Exception:
            re_slopes = {}

        # --- the OLS reference ------------------------------------------------
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ols = smf.ols(SPEC_OLS, data=d).fit()

        # --- per-district OLS slopes, for comparison -------------------------
        per_district = {}
        for district, g in d.groupby("district_id"):
            if len(g) < 5:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    m = smf.ols("y ~ rain_mm", data=g).fit()
                    per_district[str(district)] = {
                        "slope": float(m.params["rain_mm"]),
                        "p": float(m.pvalues["rain_mm"]),
                        "n": int(m.nobs),
                    }
                except Exception:
                    continue

        slopes = np.array([v["slope"] for v in per_district.values()]) if per_district else np.array([])
        results[crop] = {
            "fitted": True,
            "lrt_statistic": float(lrt),
            "lrt_p_value": p_lrt,
            "lrt_valid": bool(lrt_valid),
            "lrt_note": (
                "LRT statistic is non-negative, so the random-slope fit is a "
                "genuine optimum"
                if lrt_valid else
                "LRT statistic is negative: the random-slope model did not reach "
                "a better optimum than the random-intercept model, so the test "
                "is reported as not significant (an optimisation boundary, not "
                "evidence for H0)"
            ),
            "h0": "all district rainfall slopes are equal (random-slope variance = 0)",
            "significant_at_05": significant,
            "random_intercept_only": {
                "llf": float(ri.llf),
                "group_slope": float(ri.params["rain_mm"]),
                "group_slope_p": float(ri.pvalues["rain_mm"]),
            },
            "random_intercept_and_slope": {
                "llf": float(rs.llf),
                "group_slope": float(rs.params["rain_mm"]),
                "group_slope_p": float(rs.pvalues["rain_mm"]),
                "slope_variance": float(rs.cov_re.iloc[1, 1]) if rs.cov_re.shape[0] > 1 else 0.0,
            },
            "ols_reference": {
                "r2": float(ols.rsquared),
                "n": int(ols.nobs),
            },
            "per_district_ols_slope_summary": {
                "n_districts": int(len(slopes)),
                "mean": float(slopes.mean()) if len(slopes) else None,
                "sd": float(slopes.std(ddof=1)) if len(slopes) > 1 else None,
                "min": float(slopes.min()) if len(slopes) else None,
                "max": float(slopes.max()) if len(slopes) else None,
                "n_significant_05": int(
                    sum(1 for v in per_district.values() if v["p"] < 0.05)
                ),
            },
            "per_district_ols_slopes": per_district,
            "shrunken_random_slopes": re_slopes,
        }

        log(
            f"  {crop:20s} LRT chi2={lrt:7.3f}  p={p_lrt:.4f}  "
            f"({'district slopes DIFFER' if significant else 'no evidence slopes differ'})"
        )
        if per_district:
            log(
                f"    per-district OLS slopes: mean {slopes.mean():+.6f} "
                f"sd {slopes.std(ddof=1):.6f}  "
                f"range {slopes.min():+.6f} to {slopes.max():+.6f}  "
                f"({sum(1 for v in per_district.values() if v['p'] < 0.05)}/{len(per_district)} "
                f"significant at p<0.05)"
            )

    out = cfg.PROCESSED / "slope_heterogeneity.json"
    cfg.write_json(
        out,
        {
            "artifact": "slope_heterogeneity",
            "created_utc": cfg.utc_now_iso(),
            "data_version": VERSION,
            "seed": RANDOM_STATE,
            "model": "MixedLM(yield ~ rain_mm, groups=district_id, re_formula='~rain_mm')",
            "test": "likelihood-ratio test of H0: random-slope variance = 0",
            "crops": results,
        },
    )
    log(f"  wrote {out.name}")


if __name__ == "__main__":
    main()
