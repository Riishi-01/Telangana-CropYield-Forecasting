"""Step 08 - Out-of-sample validation against a district-crop median baseline.

Split (SRS §5.5) - CHRONOLOGICAL ONLY, never random:

    train : seasons <= 2019-20   (2016-17 .. 2019-20, 4 seasons)
    test  : seasons >= 2020-21   (2020-21 .. 2022-23, 3 seasons)

Random splits leak information across autocorrelated weather years, so no
random split appears anywhere in this project (acceptance criterion A8).

Baseline: the district-crop median yield computed on the TRAIN period only.
Metric : out-of-sample RMSE and MAE vs. the baseline, and the skill score

    skill = 1 - RMSE_model / RMSE_baseline

A positive skill is NOT guaranteed.  If the skill is <= 0 the weather-only
model does not beat the median, and that is reported as the finding
(GUIDE §9).

CONVENTION for the test period: the season fixed effects of the test seasons
are not estimable from the train data.  Test rows are therefore predicted
with the reference season's effect (its season dummy is zero), i.e. the
prediction is conditional on no additional year effect beyond the reference.
This is stated in the README and in the dashboard.

Authority: plan/SRS.md §5.5 ; plan/GUIDE.md Step 9.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import patsy
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

VERSION = cfg.data_version()
SPEC = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(season)"
SPEC_NO_SEASON_FE = "y ~ rain_mm + I(rain_mm ** 2) + C(district_id)"


def main() -> None:
    cfg.check_determinism()
    log("Step 08: out-of-sample validation (chronological split)")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    primary = panel[panel["is_primary_panel"]].copy()

    results: dict[str, dict] = {}

    for crop in cfg.MODELLED_CROPS:
        d = primary[primary["crop"] == crop].copy()
        if len(d) < 60:
            continue

        train = d[d["season"] <= cfg.TRAIN_LAST_SEASON].copy()
        test = d[d["season"] >= cfg.TEST_FIRST_SEASON].copy()
        if train.empty or test.empty:
            log(f"  {crop}: empty train or test block - skipped")
            continue

        train["y"] = train["yield"]
        test["y"] = test["yield"]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = smf.ols(SPEC, data=train).fit()

        # --- design matrix for the test block, built on the TRAIN categories ---
        train_seasons = sorted(train["season"].unique())
        train_districts = sorted(train["district_id"].unique())
        ref_season = train_seasons[0]
        ref_district = train_districts[0]

        unseen_seasons = sorted(set(test["season"]) - set(train_seasons))
        unseen_districts = sorted(set(test["district_id"]) - set(train_districts))
        if unseen_districts:
            log(f"  WARNING {crop}: districts absent from train {unseen_districts} "
                "- mapped to the reference district")

        design = test.copy()
        design["season"] = design["season"].map(
            lambda s: s if s in train_seasons else ref_season
        )
        design["district_id"] = design["district_id"].map(
            lambda d_: d_ if d_ in train_districts else ref_district
        )
        x_train = patsy.dmatrix(SPEC.split("~", 1)[1], train, return_type="dataframe")
        # Build the test design on the TRAIN categories, then predict from the
        # original-variable frame so statsmodels re-uses the fitted design_info.
        x_test = patsy.build_design_matrices(
            [x_train.design_info], design, return_type="dataframe"
        )[0]
        assert list(x_test.columns) == list(x_train.columns), "design matrix mismatch"
        pred = np.asarray(model.predict(design), dtype=float)

        actual = test["yield"].to_numpy(dtype=float)

        # --- baseline: district-crop median on the TRAIN period only ---------
        med_district = train.groupby("district_id")["yield"].median()
        med_crop = train["yield"].median()
        base = test["district_id"].map(med_district).fillna(med_crop).to_numpy(dtype=float)

        rmse_model = float(np.sqrt(np.mean((actual - pred) ** 2)))
        rmse_base = float(np.sqrt(np.mean((actual - base) ** 2)))
        mae_model = float(np.mean(np.abs(actual - pred)))
        mae_base = float(np.mean(np.abs(actual - base)))
        skill = float(1.0 - rmse_model / rmse_base) if rmse_base > 0 else float("nan")
        skill_mae = float(1.0 - mae_model / mae_base) if mae_base > 0 else float("nan")

        # --- second specification: no season fixed effects --------------------
        # The primary specification differences out the common year effect, so
        # the test years - whose year effect is unobserved - cannot be
        # predicted.  This second specification keeps the absolute rainfall
        # level, so it can use the test-year rainfall directly.  It is a
        # robustness check on the evaluation, not a replacement of the primary
        # specification.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model_nf = smf.ols(SPEC_NO_SEASON_FE, data=train).fit()
        x_train_nf = patsy.dmatrix(
            SPEC_NO_SEASON_FE.split("~", 1)[1], train, return_type="dataframe"
        )
        design_nf = test.copy()
        design_nf["district_id"] = design_nf["district_id"].map(
            lambda d_: d_ if d_ in train_districts else ref_district
        )
        x_test_nf = patsy.build_design_matrices(
            [x_train_nf.design_info], design_nf, return_type="dataframe"
        )[0]
        assert list(x_test_nf.columns) == list(x_train_nf.columns)
        pred_nf = np.asarray(model_nf.predict(design_nf), dtype=float)
        rmse_model_nf = float(np.sqrt(np.mean((actual - pred_nf) ** 2)))
        mae_model_nf = float(np.mean(np.abs(actual - pred_nf)))
        skill_nf = (
            float(1.0 - rmse_model_nf / rmse_base) if rmse_base > 0 else float("nan")
        )
        skill_nf_mae = (
            float(1.0 - mae_model_nf / mae_base) if mae_base > 0 else float("nan")
        )

        results[crop] = {
            "unit": str(d["unit"].iloc[0]),
            "train_seasons": train_seasons,
            "test_seasons": sorted(test["season"].unique()),
            "n_train_rows": int(len(train)),
            "n_test_rows": int(len(test)),
            "n_train_district_seasons": int(
                train[["district_id", "season"]].drop_duplicates().shape[0]
            ),
            "n_test_district_seasons": int(
                test[["district_id", "season"]].drop_duplicates().shape[0]
            ),
            "train_r2": float(model.rsquared),
            "rmse_model": rmse_model,
            "rmse_baseline": rmse_base,
            "mae_model": mae_model,
            "mae_baseline": mae_base,
            "skill_rmse": skill,
            "skill_mae": skill_mae,
            "beats_baseline": bool(skill > 0),
            "no_season_fe": {
                "formula": SPEC_NO_SEASON_FE.replace("y ~", "yield ~", 1),
                "train_r2": float(model_nf.rsquared),
                "rmse_model": rmse_model_nf,
                "mae_model": mae_model_nf,
                "skill_rmse": skill_nf,
                "skill_mae": skill_nf_mae,
                "beats_baseline": bool(skill_nf > 0),
            },
            "test_season_effect_convention": (
                "test seasons are not in the train block, so their season fixed "
                "effect is set to the reference season (dummy = 0)"
            ),
            "unseen_test_seasons": unseen_seasons,
        }

        log(
            f"  {crop:20s} train {len(train):3d} / test {len(test):3d}   "
            f"RMSE model {rmse_model:.4f} vs baseline {rmse_base:.4f}   "
            f"skill {skill:+.3f}  ({'beats' if skill > 0 else 'does NOT beat'} the median)"
        )
        log(
            f"    no season FE: RMSE {rmse_model_nf:.4f}  skill {skill_nf:+.3f}  "
            f"({'beats' if skill_nf > 0 else 'does NOT beat'} the median)"
        )

    summary = cfg.read_json(cfg.PROCESSED / "model_summary.json")
    summary["validation"] = {
        "created_utc": cfg.utc_now_iso(),
        "split": "chronological",
        "train_last_season": cfg.TRAIN_LAST_SEASON,
        "test_first_season": cfg.TEST_FIRST_SEASON,
        "spec": SPEC.replace("y ~", "yield ~", 1),
        "baseline": "district-crop median yield computed on the train period only",
        "skill_definition": "1 - RMSE_model / RMSE_baseline",
        "note": "a non-positive skill score is a reportable result, not a failure",
        "crops": results,
    }
    cfg.write_json(cfg.PROCESSED / "model_summary.json", summary)
    log("  wrote data/processed/model_summary.json (validation block)")

    # --- gate G9 -------------------------------------------------------------
    for crop, res in results.items():
        assert "skill_rmse" in res and "rmse_baseline" in res
    log("  gate G9: chronological split, skill reported at any sign")


if __name__ == "__main__":
    main()
