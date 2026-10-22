"""Step 12 - Season-window sensitivity for the response curve.

The official kharif analysis window is 1 Jun - 30 Sep (the sowing window, SRS
§5.1).  But Jun-Sep is not the growing season: cotton and arhar run to Nov-Dec,
so late-season rainfall is undercounted - a stated limitation (SRS §9 item 6).

This script turns that limitation into a test.  It recomputes seasonal rainfall
under three windows and refits the Stage 1 specification for each:

  jul_sep  (7-9)   narrower than the sowing window
  jun_sep  (6-9)   the base window used everywhere else
  jun_oct  (6-10)  wider, capturing late-season rain

GATE: the jun_sep row must reproduce the primary Stage 1 fit exactly (b1, b2,
R2, vertex), which proves the recomputation matches the shipped panel.  If it
does not, the feature pipeline and this script have diverged and the build stops.

Authority: plan/SRS.md §5.1, §9 ; plan/GUIDE.md Step 7.
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
SPEC = "y ~ rain_win + I(rain_win ** 2) + C(district_id) + C(season)"

WINDOWS = {
    "jul_sep": dict(label="Jul-Sep", months=(7, 9), days=92,
                    note="narrower than the sowing window"),
    "jun_sep": dict(label="Jun-Sep", months=(6, 9), days=122,
                    note="the base kharif sowing window"),
    "jun_oct": dict(label="Jun-Oct", months=(6, 10), days=153,
                    note="wider, captures late-season rainfall"),
}


def window_rain(daily: pd.DataFrame, months: tuple[int, int]) -> pd.DataFrame:
    """Seasonal rainfall per district x season for one window."""
    m1, m2 = months
    d = daily[daily["date"].dt.month.between(m1, m2)].copy()
    return (
        d.groupby(["district_slug", "season"], as_index=False)["precip_mm"]
        .sum()
        .rename(columns={"precip_mm": "rain_win"})
    )


def fit(data: pd.DataFrame) -> dict:
    work = data.copy()
    work["y"] = work["yield"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = smf.ols(SPEC, data=work).fit()
    b1 = float(model.params["rain_win"])
    b2 = float(model.params["I(rain_win ** 2)"])
    p1 = float(model.pvalues["rain_win"])
    p2 = float(model.pvalues["I(rain_win ** 2)"])
    vertex = None
    vertex_ci = None
    if abs(b2) > 1e-12:
        v = -b1 / (2.0 * b2)
        d_b1 = -1.0 / (2.0 * b2)
        d_b2 = b1 / (2.0 * b2**2)
        cov = model.cov_params()
        var = (d_b1**2 * cov.loc["rain_win", "rain_win"]
               + d_b2**2 * cov.loc["I(rain_win ** 2)", "I(rain_win ** 2)"]
               + 2.0 * d_b1 * d_b2 * cov.loc["rain_win", "I(rain_win ** 2)"])
        se = float(np.sqrt(max(var, 0.0)))
        vertex_ci = [v - 1.959963985 * se, v + 1.959963985 * se]
        if b2 < 0 and p2 < 0.05:
            vertex = v
    return {
        "n": int(model.nobs),
        "b1": b1, "p1": p1, "b2": b2, "p2": p2,
        "r2": float(model.rsquared), "adj_r2": float(model.rsquared_adj),
        "vertex_mm": vertex,
        "vertex_ci95_mm": vertex_ci,
        "vertex_reported": vertex is not None,
        "rain_min": float(data["rain_win"].min()),
        "rain_max": float(data["rain_win"].max()),
    }


def main() -> None:
    cfg.check_determinism()
    log("Step 12: season-window sensitivity")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    primary = panel[panel["is_primary_panel"]].copy()
    summary = cfg.read_json(cfg.PROCESSED / "model_summary.json")

    daily = pd.read_parquet(cfg.INTERIM / "weather_daily.parquet")
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily[daily["date"] <= pd.Timestamp(cfg.INGEST_END)].copy()
    daily["season_year"] = daily["date"].dt.year
    daily["season"] = daily["season_year"].map(cfg.season_label)
    daily = daily[daily["date"].dt.month >= 6]

    # precompute the rainfall per window once
    rain_by_window = {name: window_rain(daily, w["months"]) for name, w in WINDOWS.items()}

    results: dict = {}
    for crop in cfg.TARGET_CROPS:
        d0 = primary[primary["crop"] == crop]
        if d0.empty:
            continue
        results[crop] = {}
        for name, w in WINDOWS.items():
            rain = rain_by_window[name]
            merged = d0.merge(rain, on=["district_slug", "season"], how="left")
            assert merged["rain_win"].notna().all(), f"{crop}/{name}: missing rainfall"
            results[crop][name] = fit(merged)
            results[crop][name]["label"] = w["label"]
            results[crop][name]["note"] = w["note"]
        # ---- gate: base window reproduces the shipped primary fit -----------
        base = results[crop]["jun_sep"]
        shipped = summary["crops"][crop]["primary"]
        for field, got, want in [
            ("b1", base["b1"], shipped["b1"]),
            ("b2", base["b2"], shipped["b2"]),
            ("r2", base["r2"], shipped["r2"]),
        ]:
            if not np.isclose(got, want, rtol=1e-6, atol=1e-9):
                raise SystemExit(
                    f"FATAL: {crop} base window {field} = {got} does not match the "
                    f"shipped primary fit {want} - the feature pipeline and this "
                    "script have diverged"
                )
        log(f"  {crop:20s} base-window gate PASSED")

    # ---- report ------------------------------------------------------------
    print("\n  --- rainfall by window (primary panel, district-seasons) ---")
    print(f"  {'crop':20s} " + "  ".join(f"{WINDOWS[w]['label']:>22s}" for w in WINDOWS))
    for crop in cfg.TARGET_CROPS:
        cells = []
        for w in WINDOWS:
            r = results[crop][w]
            v = f"R* {r['vertex_mm']:.0f}mm" if r["vertex_reported"] else "no vertex"
            cells.append(f"p2={r['p2']:.3f} {v}")
        print(f"  {crop:20s} " + "  ".join(f"{c:>22s}" for c in cells))

    out = cfg.PROCESSED / "window_sensitivity.json"
    cfg.write_json(out, {
        "created_utc": cfg.utc_now_iso(),
        "data_version": VERSION,
        "spec": SPEC.replace("y ~", "yield ~", 1),
        "purpose": "tests whether the 'no rainfall optimum' conclusion depends on the "
        "Jun-Sep sowing window; the base window reproduces the shipped Stage 1 fit "
        "exactly (gate)",
        "windows": {k: {"label": v["label"], "months": list(v["months"]),
                        "days_in_window": v["days"], "note": v["note"]}
                    for k, v in WINDOWS.items()},
        "crops": results,
    })
    log(f"  wrote {out}")

    # summarise whether the conclusion is window-dependent
    print("\n  --- does the conclusion depend on the window? ---")
    for crop in cfg.TARGET_CROPS:
        verdicts = {w: results[crop][w]["vertex_reported"] for w in WINDOWS}
        stable = len(set(verdicts.values())) == 1
        state = "vertex reported" if verdicts["jun_sep"] else "no vertex"
        print(f"    {crop:20s} {state} in all windows" if stable
              else f"    {crop:20s} DEPENDS ON WINDOW: {verdicts}")


if __name__ == "__main__":
    main()