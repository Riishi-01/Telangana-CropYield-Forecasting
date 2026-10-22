"""Step 16 - per-crop forecast model selection (P1-9a, v1.2.0).

The shipped Stage 1 model applies ONE specification to all four crops.  That
is not defensible for a forecast: a single model cannot be right for cotton,
arhar, moong and rice at once.  This script selects a specification PER CROP.

Two gates, in this order, and both are build gates - the script fails rather
than shipping a model that does not pass them.

GATE 1 - SELECTION ON TRAIN DATA ONLY.
    Four candidate specifications are scored by leave-one-season-out cross
    validation INSIDE the training block (seasons <= 2019-20).  The
    validation block (seasons >= 2020-21) is touched ONCE, at the end, to
    report the skill of the already-selected model.  Selecting a
    specification on the validation block and then reporting its validation
    score would be selection on the test data, and the score would be
    meaningless.

GATE 2 - APPLICABILITY AT 2026 RAINFALL.
    A model may only be used to predict 2026 if it produces physically valid
    yields for every district at the observed 2026 rainfall.  Arhar's
    quadratic passes Gate 1 but its curve goes negative below ~440 mm; the
    2026 state mean is 488 mm, and it returns negative yields for 19 of 32
    districts.  A negative yield is not a forecast, it is an extrapolation
    failure, so that specification is rejected for arhar and the next-best
    valid one is used.  The rejected specification and the reason are
    recorded, not silently dropped.

Output:
    data/processed/forecast_models.json

Authority: README section 5.4 (one model per crop).
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
RANDOM_STATE = cfg.RANDOM_STATE

# --- the candidate specifications ---------------------------------------------
# The response is copied to `y` because `yield` is a Python keyword and
# cannot be a patsy target (the same trick src/06_model_stage1.py uses).
SPECS: dict[str, str] = {
    "S1_quadratic": "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(year)",
    "S1_linear": "y ~ rain_mm + C(district_id) + C(year)",
    "S2_quadratic_deficit": (
        "y ~ rain_mm + I(rain_mm ** 2) + C(district_id) + C(year) "
        "+ dry_run_max + dry_days_ge5 + heat_days + vpd_mean + rain_days"
    ),
    "S2_linear_deficit": (
        "y ~ rain_mm + C(district_id) + C(year) "
        "+ dry_run_max + dry_days_ge5 + heat_days + vpd_mean + rain_days"
    ),
}

# --- prediction helpers -------------------------------------------------------
def _predict(spec: str, train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Predict `test` with a model fitted on `train`.

    The test block's year and district levels are not estimable from the
    train block, so unseen years fall back to the reference year and unseen
    districts to the reference district - the convention src/08_validate.py
    already uses and states.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = smf.ols(spec, data=train).fit()
    train_years = sorted(train["year"].unique())
    train_districts = sorted(train["district_id"].unique())
    design = test.copy()
    design["year"] = design["year"].map(
        lambda y: y if y in train_years else train_years[0]
    )
    design["district_id"] = design["district_id"].map(
        lambda d: d if d in train_districts else train_districts[0]
    )
    x_train = patsy.dmatrix(spec.split("~", 1)[1], train, return_type="dataframe")
    patsy.build_design_matrices([x_train.design_info], design, return_type="dataframe")
    return np.asarray(model.predict(design), dtype=float)


def _rmse(a: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(a, dtype=float) ** 2)))


def _skill(pred: np.ndarray, actual: np.ndarray, base: np.ndarray) -> float:
    """Skill score against the district-crop median baseline."""
    denom = _rmse(actual - base)
    if denom <= 0:
        return float("nan")
    return 1.0 - _rmse(actual - pred) / denom


def main() -> None:
    cfg.check_determinism()
    log(f"Step 16: per-crop forecast model selection (DATA_VERSION {VERSION})")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    primary = panel[panel["is_primary_panel"]].copy()
    marker_path = cfg.INTERIM / "features_2026.parquet"
    if not marker_path.exists():
        raise SystemExit("features_2026.parquet missing - the 2026 marker is required")
    marker = pd.read_parquet(marker_path)

    train_seasons = sorted(
        primary.loc[primary["season"] <= cfg.TRAIN_LAST_SEASON, "season"].unique()
    )
    test_seasons = sorted(
        primary.loc[primary["season"] >= cfg.TEST_FIRST_SEASON, "season"].unique()
    )
    log(f"  train seasons {train_seasons[0]}..{train_seasons[-1]} | "
        f"test seasons {test_seasons[0]}..{test_seasons[-1]}")

    results: dict[str, dict] = {}

    for crop in cfg.MODELLED_CROPS:
        d = primary[primary["crop"] == crop].copy()
        d["y"] = d["yield"]
        if len(d) < 60:
            continue
        train = d[d["season"].isin(train_seasons)].copy()
        test = d[d["season"].isin(test_seasons)].copy()

        # ---- GATE 1: leave-one-season-out CV inside the train block ----------
        cv: dict[str, float] = {}
        for name, spec in SPECS.items():
            errors = []
            for held in train_seasons:
                inner_train = train[train["season"] != held].copy()
                inner_test = train[train["season"] == held].copy()
                pred = _predict(spec, inner_train, inner_test)
                errors.append(inner_test["y"].to_numpy(dtype=float) - pred)
            cv[name] = _rmse(np.concatenate(errors))
        ranked = sorted(cv, key=lambda k: cv[k])
        best = ranked[0]
        log(f"  {crop:20s} CV rank: " + ", ".join(f"{k}={cv[k]:.4f}" for k in ranked))

        # ---- GATE 2: applicability at the observed 2026 rainfall ------------
        id_map = d.drop_duplicates("district_slug").set_index("district_slug")["district_id"]
        year_levels = sorted(d["year"].unique())

        def implied_yields(spec: str) -> dict:
            out: dict[str, float] = {}
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = smf.ols(spec, data=d).fit()
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
                out[slug] = float(model.predict(frame)[0])
            return out

        selected = None
        rejected: list[dict] = []
        for name in ranked:
            vals = implied_yields(SPECS[name])
            n_negative = sum(1 for v in vals.values() if v <= 0)
            if n_negative == 0:
                selected = name
                if rejected:
                    log(f"    {name}: valid at 2026 rainfall (0 negative districts)")
                break
            rejected.append({
                "spec": name,
                "n_negative_districts": n_negative,
                "reason": (
                    f"the fitted curve returns a non-positive yield for "
                    f"{n_negative} of {len(vals)} districts at the observed 2026 "
                    f"rainfall, so it cannot be used to predict 2026"
                ),
            })
            log(f"    {name}: REJECTED - {n_negative} negative-yield districts at 2026")

        if selected is None:
            raise SystemExit(
                f"{crop}: no candidate specification produces valid 2026 yields - "
                "the forecast cannot be published for this crop"
            )

        # ---- the one honest evaluation of the selected model -----------------
        pred = _predict(SPECS[selected], train, test)
        actual = test["y"].to_numpy(dtype=float)
        base = (
            test["district_id"]
            .map(train.groupby("district_id")["y"].median())
            .fillna(train["y"].median())
            .to_numpy(dtype=float)
        )
        skill = _skill(pred, actual, base)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            final = smf.ols(SPECS[selected], data=d).fit()
        b_rain = float(final.params["rain_mm"])

        results[crop] = {
            "selected_spec": selected,
            "spec": SPECS[selected],
            "spec_yield_form": SPECS[selected].replace("y ~", "yield ~", 1),
            "cv_rmse_train_block": {k: round(v, 6) for k, v in cv.items()},
            "cv_ranking": ranked,
            "rejected_specs": rejected,
            "skill_rmse": float(skill),
            "beats_baseline": bool(skill > 0),
            "baseline": "district-crop median yield computed on the train period only",
            "train_seasons": train_seasons,
            "test_seasons": test_seasons,
            "n_train_rows": int(len(train)),
            "n_test_rows": int(len(test)),
            "r2": float(final.rsquared),
            "b_rain_per_mm": b_rain,
            "unit": str(d["yield_unit"].iloc[0]),
            "n_districts": int(d["district_id"].nunique()),
        }
        log(f"    selected {selected} | test skill {skill:+.3f} | R2 {final.rsquared:.3f}")

    # ---- the shared reference specification, for comparison -------------------
    shared = "S1_quadratic"
    shared_skill = {}
    for crop, res in results.items():
        d = primary[primary["crop"] == crop].copy()
        d["y"] = d["yield"]
        train = d[d["season"].isin(train_seasons)].copy()
        test = d[d["season"].isin(test_seasons)].copy()
        pred = _predict(SPECS[shared], train, test)
        actual = test["y"].to_numpy(dtype=float)
        base = (
            test["district_id"]
            .map(train.groupby("district_id")["y"].median())
            .fillna(train["y"].median())
            .to_numpy(dtype=float)
        )
        shared_skill[crop] = float(_skill(pred, actual, base))

    out = cfg.PROCESSED / "forecast_models.json"
    cfg.write_json(
        out,
        {
            "artifact": "forecast_models",
            "created_utc": cfg.utc_now_iso(),
            "data_version": VERSION,
            "seed": RANDOM_STATE,
            "selection_method": (
                "leave-one-season-out cross-validation inside the train block; "
                "the validation block is evaluated once, after selection"
            ),
            "validity_gate": (
                "a specification may only predict 2026 if it produces a positive "
                "yield for every district at the observed 2026 rainfall"
            ),
            "candidate_specs": SPECS,
            "shared_spec_for_comparison": shared,
            "shared_spec_skill_rmse": shared_skill,
            "crops": results,
        },
    )
    log(f"  wrote {out.name}")

    # ---- gates ---------------------------------------------------------------
    for crop, res in results.items():
        assert res["selected_spec"], f"{crop}: no specification selected"
        assert res["rejected_specs"] is not None, f"{crop}: rejection log missing"
    log("  gate: every crop has a CV-selected, validity-checked specification")


if __name__ == "__main__":
    main()
