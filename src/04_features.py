"""Step 04 - Derive kharif-season weather features per district and season.

Input : data/interim/weather_daily.parquet
Output: data/interim/features.parquet        one row per district x season year
        data/interim/features_2026.parquet   the 2026 marker reading (if present)

Feature windows:
  analysis window  1 Jun - 30 Sep  (official kharif sowing window)
  dry-spell window 1 Jun - 31 Oct  (wider, so late-season spells are captured)

CAUSALITY: every window is closed at a fixed calendar boundary
that falls *before* the crop is harvested.  No feature uses a trailing window
that peeks past the end of its own window, and no feature is shifted forward
onto a later target.  The window direction is stated at every computation.

Authority: README section 3 (the features table).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

log = C.log
C.ensure_dirs()

RAIN_DAY_MM = 2.5      # WMO "rain day" definition
HEAT_DAY_C = 35.0      # Tmax above this counts as a heat-stress day


def longest_dry_run(precip: np.ndarray, threshold: float = RAIN_DAY_MM) -> int:
    """Longest run of consecutive days with precip < threshold.

    The scan walks the array forward in time and only ever looks at the day it
    is currently on - the window is closed at the end of the series, never
    extended by later data.
    """
    best = 0
    run = 0
    for value in precip:
        if value < threshold:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def days_in_long_runs(precip: np.ndarray, min_len: int = 5,
                      threshold: float = RAIN_DAY_MM) -> int:
    """Number of days that sit inside a dry run of at least `min_len` days.

    Forward scan over the same closed window; a run is counted once its length
    is known, i.e. only from information available up to that point.
    """
    total = 0
    run = 0
    for value in precip:
        if value < threshold:
            run += 1
        else:
            if run >= min_len:
                total += run
            run = 0
    if run >= min_len:
        total += run
    return total


def season_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Compute the feature set for one district's daily series."""
    rows = []
    for (slug, year), g in daily.groupby(["district_slug", "year"]):
        g = g.sort_values("date")

        # --- analysis window: 1 Jun - 30 Sep of the season year --------------
        # Window opens at 1 Jun and closes at 30 Sep of the same calendar year.
        a = g[(g["date"].dt.month >= C.ANALYSIS_START_MMDD[0])
              & (g["date"].dt.month <= C.ANALYSIS_END_MMDD[0])]
        # (the ingest window starts on 1 Jun, so a month filter is exact here)

        # --- dry-spell window: 1 Jun - 31 Oct of the season year -------------
        # Wider window so spells that begin late are not truncated. Closes
        # 31 Oct, still before harvest for the kharif crop.
        d = g[(g["date"].dt.month >= C.FEATURE_WINDOW_END_MMDD[0] - 4)
              & (g["date"].dt.month <= C.FEATURE_WINDOW_END_MMDD[0])]

        precip_a = a["precip_mm"].to_numpy(dtype=float)
        precip_d = d["precip_mm"].to_numpy(dtype=float)

        rows.append(
            {
                "district_slug": slug,
                "year": int(year),
                "season": C.season_label(int(year)),
                "n_days_analysis": int(len(a)),
                "n_days_dryspell": int(len(d)),
                "rain_mm": round(float(np.nansum(precip_a)), 2),
                "rain_days": int((precip_a >= RAIN_DAY_MM).sum()),
                "dry_run_max": int(longest_dry_run(precip_d)),
                "dry_days_ge5": int(days_in_long_runs(precip_d, min_len=5)),
                "heat_days": int((a["tmax_c"].to_numpy(dtype=float) > HEAT_DAY_C).sum()),
                "vpd_mean": round(float(np.nanmean(a["vpd_max_kpa"].to_numpy(dtype=float))), 4),
                "tmax_mean": round(float(np.nanmean(a["tmax_c"].to_numpy(dtype=float))), 4),
                "tmin_mean": round(float(np.nanmean(a["tmin_c"].to_numpy(dtype=float))), 4),
                "srad_mean": round(float(np.nanmean(a["srad_mj"].to_numpy(dtype=float))), 4),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    C.check_determinism()
    log("Step 04: feature engineering")

    weather = pd.read_parquet(C.INTERIM / "weather_daily.parquet")
    weather["date"] = pd.to_datetime(weather["date"])

    main_mask = weather["date"] <= pd.Timestamp(C.INGEST_END)
    analysis = weather[main_mask].copy()
    # A kharif season is identified by the calendar year in which it opens:
    # June-October of year Y is season Y-YY.  The mapping is a named
    # constant (common.YEAR_MAPPING) and is verified by gate G1 in step 05.
    assert C.SEASON_OPENS_IN_CALENDAR_YEAR, "year mapping constant flipped"
    analysis["year"] = analysis["date"].dt.year
    analysis = analysis[analysis["date"].dt.month >= 6]

    features = season_features(analysis)
    features = features.sort_values(["district_slug", "year"]).reset_index(drop=True)
    out = C.INTERIM / "features.parquet"
    features.to_parquet(out, index=False)
    log(f"  wrote {out} rows={len(features)}")

    # --- gates --------------------------------------------------------------
    assert (features["n_days_analysis"] == 122).all(), "analysis window must be 122 days"
    assert (features["n_days_dryspell"] == 153).all(), "dry-spell window must be 153 days"
    assert (features["rain_mm"] > 0).all(), "zero rainfall season"
    assert features["dry_run_max"].between(0, 153).all()
    assert features["heat_days"].between(0, 122).all()

    print("\n  --- state-mean kharif rainfall by season (mm) ---")
    state = features.groupby("season")["rain_mm"].agg(["mean", "min", "max"]).round(1)
    print(state.to_string())

    print("\n  --- feature ranges ---")
    print(
        features[
            ["rain_mm", "rain_days", "dry_run_max", "dry_days_ge5", "heat_days",
             "vpd_mean", "tmax_mean"]
        ]
        .describe()
        .loc[["min", "mean", "max"]]
        .round(2)
        .to_string()
    )

    # --- 2026 marker (present only once the marker window has been fetched) --
    marker_mask = weather["date"] >= pd.Timestamp(C.MARKER_START)
    if marker_mask.any():
        m = weather[marker_mask].copy()
        m["year"] = m["date"].dt.year
        m = m[m["date"].dt.month >= 6]
        f2026 = season_features(m)
        f2026 = f2026.sort_values("district_slug").reset_index(drop=True)
        f2026.to_parquet(C.INTERIM / "features_2026.parquet", index=False)
        log(f"  wrote features_2026.parquet rows={len(f2026)} "
            f"mean rain {f2026['rain_mm'].mean():.0f} mm")
    else:
        log("  2026 marker window not present yet - skipping marker features")

    C.write_json(
        C.MANIFESTS / "features.json",
        {
            "artifact": "features.parquet",
            "created_utc": C.utc_now_iso(),
            "analysis_window": ["06-01", "09-30"],
            "dry_spell_window": ["06-01", "10-31"],
            "rain_day_threshold_mm": RAIN_DAY_MM,
            "rain_day_definition": "WMO standard (>= 0.1 inch / 2.5 mm)",
            "heat_day_threshold_c": HEAT_DAY_C,
            "rows": int(len(features)),
            "districts": int(features["district_slug"].nunique()),
            "seasons": sorted(features["season"].unique().tolist()),
            "sha256": C.sha256_file(out),
        },
    )
    log("  manifest written: data/manifests/features.json")


if __name__ == "__main__":
    main()
