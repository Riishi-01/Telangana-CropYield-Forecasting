"""Step 05 - Build the analysis panel from the cleaned 4-crop dataset.

Joins the preprocessed yields (data/processed/crops_kharif_clean.parquet) to the
ERA5 season features on district x season, tags the era, and adds the
leakage-guarded yield anomaly.

LEAKAGE GUARD: the anomaly denominator (the median yield for a
district-crop) is computed on the TRAIN seasons only (2016-17..2019-20) and is
then applied to every row of that district-crop.  Test-period rows never
influence their own baseline.

Outputs:
  data/processed/panel_v<version>.parquet   tidy long panel (one row per
                                            district x season x crop)
  data/processed/analysis_table_v<version>.csv   one row per district x season
                                            (no repeated weather) - the
                                            no-redundancy table for reading

Authority: README section 4 (leakage guard) and section 3 (the panel).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

VERSION = cfg.data_version()
TRAIN_LAST = cfg.TRAIN_LAST_SEASON


def main() -> None:
    cfg.check_determinism()
    log(f"Step 05: panel build (DATA_VERSION {VERSION})")

    clean = pd.read_parquet(cfg.PROCESSED / "crops_kharif_clean.parquet")
    feat = pd.read_parquet(cfg.INTERIM / "features.parquet")
    districts = pd.read_csv(cfg.GEO / "districts.csv")

    # -- join yields to season features ---------------------------------------
    panel = clean.merge(
        feat.drop(columns=["year"], errors="ignore"),
        on=["district_slug", "season"], how="left", validate="many_to_one",
    )
    assert panel["rain_mm"].notna().all(), "a yield row has no weather features"

    # -- era tagging and ids --------------------------------------------------
    panel["era"] = panel["season"].map(cfg.season_era)
    panel["district_id"] = panel["district_slug"] + "__" + panel["era"]
    panel["is_primary_panel"] = panel["era"] == "post2016"

    labels = districts.drop_duplicates("district_slug").set_index("district_slug")
    panel["district_label"] = panel["district_slug"].map(labels["des_name"])
    panel["lat"] = panel["district_slug"].map(labels["lat"])
    panel["lon"] = panel["district_slug"].map(labels["lon"])

    # -- leakage-guarded anomaly (train-period median only) ------------------
    train = panel["season"] <= TRAIN_LAST
    train_medians = (
        panel[train].groupby(["district_id", "crop"])["yield"].median()
        .rename("base_yield")
    )
    crop_medians = panel[train].groupby("crop")["yield"].median().rename("crop_base_yield")
    panel = panel.join(train_medians, on=["district_id", "crop"])
    panel = panel.join(crop_medians, on="crop")
    panel["base_yield"] = panel["base_yield"].fillna(panel["crop_base_yield"])
    panel["yield_anom_pct"] = (100.0 * (panel["yield"] / panel["base_yield"] - 1.0)).round(4)

    # -- deterministic order and types ---------------------------------------
    panel = panel.sort_values(["district_id", "season", "crop"],
                              kind="mergesort").reset_index(drop=True)
    cols = [
        "district_id", "district_slug", "district_label", "era", "season",
        "year", "is_primary_panel", "crop", "area_ha", "area_unit",
        "production", "production_unit", "yield", "yield_reported", "yield_unit",
        "base_yield", "yield_anom_pct", "lat", "lon",
        "rain_mm", "rain_days", "dry_run_max", "dry_days_ge5", "heat_days",
        "vpd_mean", "tmax_mean", "tmin_mean", "srad_mean",
    ]
    panel = panel[cols]
    for col in panel.columns:
        if panel[col].dtype == "float64":
            panel[col] = panel[col].round(6)

    out = cfg.PROCESSED / f"panel_v{VERSION}.parquet"
    panel.to_parquet(out, index=False)
    log(f"  wrote {out.name} rows={len(panel)}")

    # -- wide analysis table (one row per district x season) ------------------
    weather_cols = ["rain_mm", "rain_days", "dry_run_max", "dry_days_ge5",
                    "heat_days", "vpd_mean", "tmax_mean"]
    wide = panel.pivot_table(
        index=["district_id", "district_slug", "district_label", "era", "season",
               "year", "is_primary_panel", "lat", "lon"] + weather_cols,
        columns="crop",
        values=["yield", "yield_anom_pct"],
        aggfunc="first",
    )
    wide.columns = [f"{c}__{crop}" for c, crop in wide.columns]
    wide = wide.reset_index()
    wide = wide.sort_values(["district_id", "season"], kind="mergesort")
    for col in wide.columns:
        if wide[col].dtype == "float64":
            wide[col] = wide[col].round(6)
    wide["rain_unit"] = "mm"
    wide_path = cfg.PROCESSED / f"analysis_table_v{VERSION}.csv"
    wide.to_csv(wide_path, index=False)
    log(f"  wrote {wide_path.name} rows={len(wide)} (one row per district x season)")

    # -- gates ---------------------------------------------------------------
    prim = panel[panel["is_primary_panel"]]
    assert prim["district_id"].nunique() == 32, "primary panel must hold 32 districts"
    for crop in cfg.TARGET_CROPS:
        assert (prim["crop"] == crop).sum() > 0, f"no primary rows for {crop}"
    cotton = panel[panel["crop"] == "Cotton(lint)"]
    assert (cotton["yield_unit"] == "bales/ha").all(), "cotton must be bales/ha"
    assert not panel["yield"].isna().any()
    assert not panel["rain_mm"].isna().any()

    # -- gate G1: agricultural-year <-> calendar-year mapping ---------------
    # The spot-check row and the three-way alignment test.  A misaligned join
    # manufactures a spurious null, so this must pass before anything else is
    # interpreted.
    print("\n  --- gate G1: agricultural-year <-> calendar-year mapping ---")
    print(f"  mapping: {cfg.YEAR_MAPPING}")
    print(f"  source : {cfg.YEAR_MAPPING_SOURCE}")

    # spot-check row: Mahbubnagar 2015-16 rice against both candidate windows
    spot = panel[(panel["district_slug"] == "mahbubnagar")
                 & (panel["season"] == "2015-16")
                 & (panel["crop"] == "Rice")]
    if len(spot):
        s = spot.iloc[0]
        med = panel[(panel["district_slug"] == "mahbubnagar")
                    & (panel["crop"] == "Rice")]["yield"].median()
        fx = feat[feat["district_slug"] == "mahbubnagar"].set_index("year")
        r_open = fx.loc[s["year"], "rain_mm"]
        r_next = fx.loc[s["year"] + 1, "rain_mm"]
        print(f"  spot check: Mahbubnagar 2015-16 Rice")
        print(f"    recorded yield      {s['yield']:.3f} t/ha   (district median {med:.3f})")
        print(f"    Jun-Sep {s['year']} rainfall  {r_open:7.1f} mm   <- season opens in this year")
        print(f"    Jun-Sep {s['year'] + 1} rainfall  {r_next:7.1f} mm   <- the alternative reading")
        print(f"    the poor yield matches the {'DRY' if r_open < r_next else 'WET'} window -> "
              f"the opening year is the correct one")

    ymap = cfg.verify_year_mapping(panel, feat)
    print("  alignment test - within-district corr(yield anomaly, rainfall anomaly):")
    for lag, res in ymap["alignments"].items():
        detail = "  ".join(f"{c.split('(')[0][:8]}={v['r']:+.3f}" for c, v in res.items()
                           if isinstance(v, dict) and "r" in v)
        print(f"    {lag:7s} mean|r|={res['mean_abs_r']:.4f}   {detail}")
    print(f"  verdict: {ymap['verdict']}")
    assert ymap["best_lag"] == 0, (
        "gate G1 FAILED: the implemented year alignment is not the best of the "
        f"three (best is lag {ymap['best_lag']:+d}). The join is misaligned and "
        "every downstream result is void until it is fixed."
    )
    log("    PASS: implemented alignment is the best of the three")

    print("\n  --- primary panel: rows per crop ---")
    for crop in cfg.TARGET_CROPS:
        sub = prim[prim["crop"] == crop]
        print(f"    {crop:20s} n={len(sub):4d}  districts={sub['district_id'].nunique():2d}  "
              f"seasons={sub['season'].nunique()}  unit={sub['yield_unit'].iloc[0]}")

    # -- manifest -------------------------------------------------------------
    des_m = cfg.read_json(cfg.MANIFESTS / "des_ingest.json")
    wx_m = cfg.read_json(cfg.MANIFESTS / "weather_fetch.json")
    geo_m = cfg.read_json(cfg.MANIFESTS / "geo.json")

    cfg.write_json(
        cfg.MANIFESTS / "fetch_manifest.json",
        {
            "artifact": f"panel_v{VERSION}.parquet",
            "created_utc": cfg.utc_now_iso(),
            "data_version": VERSION,
            "weather_source": "open-meteo/era5",
            "weather_endpoint": cfg.OPEN_METEO_ARCHIVE,
            "weather_licence": cfg.WEATHER_LICENCE,
            "weather_fetched_utc": wx_m["created_utc"],
            "weather_rows": wx_m["rows"],
            "weather_sha256": wx_m["sha256"],
            "yield_source": des_m["yield_source"],
            "yield_file_sha256": des_m["yield_file_sha256"],
            "clean_dataset": "crops_kharif_clean",
            "clean_dataset_sha256": des_m["sha256"],
            "geojson_source_url": geo_m["geojson_source_url"],
            "geojson_sha256": geo_m["geojson_sha256"],
            "centroid_method": geo_m["centroid_method"],
            "temp_window": [cfg.INGEST_START, cfg.INGEST_END],
            "analysis_window": ["06-01", "09-30"],
            "dry_spell_window": ["06-01", "10-31"],
            "primary_panel": [cfg.PRIMARY_PANEL_START, "2022-23"],
            "extended_panel": [cfg.EXTENDED_PANEL_START, "2022-23"],
            "train_seasons": [cfg.PRIMARY_PANEL_START, TRAIN_LAST],
            "test_seasons": [cfg.TEST_FIRST_SEASON, "2022-23"],
            "districts": int(prim["district_id"].nunique()),
            "crops": cfg.TARGET_CROPS,
            "rows": int(len(panel)),
            "rows_primary_panel": int(len(prim)),
            "year_mapping": cfg.YEAR_MAPPING,
            "year_mapping_source": cfg.YEAR_MAPPING_SOURCE,
            "fitted_range_note": (
                "The MODELS are fitted on the primary panel "
                f"({cfg.PRIMARY_PANEL_START} -> 2022-23, {len(prim)} rows). The "
                f"dataset covers {cfg.EXTENDED_PANEL_START} -> 2022-23 "
                f"({len(panel)} rows); the earlier seasons are used for "
                "robustness only (extended-panel spec)."
            ),
            "sha256": cfg.sha256_file(out),
            "seed": cfg.SEED,
            "pythonhashseed": "0",
        },
    )
    log("  manifest written: data/manifests/fetch_manifest.json")

    # -- gate G6.3: byte-identical rebuild -----------------------------------
    log("  gate G6.3: rebuilding to check byte-identical output")
    tmp = cfg.INTERIM / "panel_rebuild_check.parquet"
    panel.to_parquet(tmp, index=False)
    a, b = cfg.sha256_file(out), cfg.sha256_file(tmp)
    tmp.unlink()
    assert a == b, "panel rebuild is not byte-identical"
    log(f"    PASS: identical ({a[:16]}...)")


if __name__ == "__main__":
    main()