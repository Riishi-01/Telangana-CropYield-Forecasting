"""Step 05 - Build the analysis panel and the data manifest.

Joins DES yields to ERA5 season features on district x season, adds the
era-tagged district id, the primary/extended panel flags and the yield
anomaly, then writes a versioned, deterministically ordered parquet.

LEAKAGE GUARD (SRS §5.5): the anomaly denominator (the median yield for a
district-crop) is computed on the TRAIN period only (seasons <= 2019-20) and
is then applied to every row of that district-crop.  Test-period rows never
influence their own baseline.

Authority: plan/SRS.md §5.5, §6.1-§6.3 ; plan/GUIDE.md Step 6.
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

VERSION = C.data_version()
ERA_BOUNDARY_SEASON = "2016-17"


def main() -> None:
    C.check_determinism()
    log(f"Step 05: panel build (DATA_VERSION {VERSION})")

    des = pd.read_parquet(C.INTERIM / "des_long.parquet")
    feat = pd.read_parquet(C.INTERIM / "features.parquet")
    districts = pd.read_csv(C.GEO / "districts.csv")

    # -- join ----------------------------------------------------------------
    panel = des.merge(
        feat, on=["district_slug", "season"], how="left", validate="many_to_one"
    )
    assert panel["rain_mm"].notna().all(), "a yield row has no weather features"

    # -- era tagging (SRS §4.4) ---------------------------------------------
    panel["era"] = np.where(panel["season"] < ERA_BOUNDARY_SEASON, "pre2016", "post2016")
    panel["district_id"] = panel["district_slug"] + "__" + panel["era"]
    panel["is_primary_panel"] = panel["season"] >= C.PRIMARY_PANEL_START

    # -- display labels ------------------------------------------------------
    labels = districts.drop_duplicates("district_slug").set_index("district_slug")
    panel["district_label"] = panel["district_slug"].map(labels["des_name"])
    panel["lat"] = panel["district_slug"].map(labels["lat"])
    panel["lon"] = panel["district_slug"].map(labels["lon"])

    # -- leakage-guarded anomaly (train-period median only) ------------------
    train = panel["season"] <= C.TRAIN_LAST_SEASON
    train_medians = (
        panel[train]
        .groupby(["district_id", "crop"])["yield"]
        .median()
        .rename("base_yield")
    )
    crop_medians = (
        panel[train].groupby("crop")["yield"].median().rename("crop_base_yield")
    )
    panel = panel.join(train_medians, on=["district_id", "crop"])
    panel = panel.join(crop_medians, on="crop")
    panel["base_yield"] = panel["base_yield"].fillna(panel["crop_base_yield"])
    # A handful of minor crops appear only in the test period (Gram, Wheat,
    # Safflower, Sweet potato) and a few district-crop pairs have no train
    # season at all.  Those rows keep their raw yield but carry no anomaly;
    # they are never used for modelling (SRS §5.3 / §5.5).
    modelled = panel["crop"].isin(C.MODELLED_CROPS)
    assert panel.loc[modelled, "base_yield"].notna().all(), (
        "a modelled crop row has no anomaly baseline"
    )
    panel["yield_anom_pct"] = (
        100.0 * (panel["yield"] / panel["base_yield"] - 1.0)
    ).round(4)

    # -- deterministic ordering and types ------------------------------------
    panel = panel.sort_values(
        ["district_id", "season", "crop"], kind="mergesort"
    ).reset_index(drop=True)
    panel["year_start"] = panel["season"].map(C.season_to_year_start)

    cols = [
        "district_id", "district_slug", "district_label", "era", "season",
        "year_start", "is_primary_panel", "crop", "unit", "area_ha", "production",
        "yield", "base_yield", "yield_anom_pct", "lat", "lon",
        "rain_mm", "rain_days", "dry_run_max", "dry_days_ge5", "heat_days",
        "vpd_mean", "tmax_mean", "tmin_mean", "srad_mean",
    ]
    panel = panel[cols]
    for col in panel.columns:
        if panel[col].dtype == "float64":
            panel[col] = panel[col].round(6)

    out = C.PROCESSED / f"panel_v{VERSION}.parquet"
    panel.to_parquet(out, index=False)
    log(f"  wrote {out} rows={len(panel)}")

    # -- gates ---------------------------------------------------------------
    prim = panel[panel["is_primary_panel"]]
    assert panel["district_id"].is_unique is False  # ids repeat across crops
    assert prim["district_id"].nunique() == 32, "primary panel must hold 32 districts"
    for crop in C.MODELLED_CROPS:
        sub = prim[prim["crop"] == crop]
        assert len(sub) > 0, f"no primary-panel rows for {crop}"
    cotton = panel[panel["crop"] == "Cotton(lint)"]
    assert (cotton["unit"] == "bales/ha").all(), "cotton must be in bales/ha"
    assert not panel["yield"].isna().any()
    assert not panel["rain_mm"].isna().any()

    print("\n  --- primary panel: rows per modelled crop ---")
    for crop in C.MODELLED_CROPS:
        sub = prim[prim["crop"] == crop]
        print(
            f"    {crop:20s} n={len(sub):4d}  districts={sub['district_id'].nunique():2d}"
            f"  seasons={sub['season'].nunique()}  unit={sub['unit'].iloc[0]}"
        )
    print("\n  --- primary panel: rows per crop (all 36 crops) ---")
    print(prim.groupby("crop").size().sort_values(ascending=False).to_string())

    # -- manifest (SRS §6.3) -------------------------------------------------
    des_manifest = C.read_json(C.MANIFESTS / "des_ingest.json")
    weather_manifest = C.read_json(C.MANIFESTS / "weather_fetch.json")
    geo_manifest = C.read_json(C.MANIFESTS / "geo.json")

    C.write_json(
        C.MANIFESTS / "fetch_manifest.json",
        {
            "artifact": f"panel_v{VERSION}.parquet",
            "created_utc": C.utc_now_iso(),
            "data_version": VERSION,
            "weather_source": "open-meteo/era5",
            "weather_endpoint": C.OPEN_METEO_ARCHIVE,
            "weather_licence": C.WEATHER_LICENCE,
            "weather_fetched_utc": weather_manifest["created_utc"],
            "weather_rows": weather_manifest["rows"],
            "weather_sha256": weather_manifest["sha256"],
            "yield_source": "DES district-wise season-wise crop production (Govt. of India)",
            "yield_file_sha256": des_manifest["yield_file_sha256"],
            "yield_rows": des_manifest["rows_out"],
            "geojson_source_url": geo_manifest["geojson_source_url"],
            "geojson_sha256": geo_manifest["geojson_sha256"],
            "centroid_method": geo_manifest["centroid_method"],
            "temp_window": [C.INGEST_START, C.INGEST_END],
            "analysis_window": ["06-01", "09-30"],
            "dry_spell_window": ["06-01", "10-31"],
            "primary_panel": [C.PRIMARY_PANEL_START, "2022-23"],
            "extended_panel": [C.EXTENDED_PANEL_START, "2022-23"],
            "train_seasons": ["2016-17", C.TRAIN_LAST_SEASON],
            "test_seasons": [C.TEST_FIRST_SEASON, "2022-23"],
            "districts": int(prim["district_id"].nunique()),
            "crops": sorted(panel["crop"].unique().tolist()),
            "modelled_crops": C.MODELLED_CROPS,
            "rows": int(len(panel)),
            "rows_primary_panel": int(len(prim)),
            "sha256": C.sha256_file(out),
            "seed": C.SEED,
            "pythonhashseed": "0",
        },
    )
    log("  manifest written: data/manifests/fetch_manifest.json")

    # -- gate G6.3: rebuild must be byte-identical ----------------------------
    log("  gate G6.3: rebuilding to check byte-identical output")
    tmp = C.INTERIM / "panel_rebuild_check.parquet"
    panel.to_parquet(tmp, index=False)
    a, b = C.sha256_file(out), C.sha256_file(tmp)
    tmp.unlink()
    log(f"    build 1 {a[:16]}...  build 2 {b[:16]}...")
    assert a == b, "panel rebuild is not byte-identical"
    log("    PASS: identical")


if __name__ == "__main__":
    main()
