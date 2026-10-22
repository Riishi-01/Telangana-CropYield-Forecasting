"""Step 01 - Preprocess the delivered DES file into a clean, focused dataset.

Input : data/horizontal_crop_vertical_year_report.xls
        (an HTML document despite the .xls extension - parsed with read_html)
Output:
  data/processed/crops_kharif_clean.parquet   the preprocessed dataset
  data/processed/crops_kharif_clean.csv       the same, for Excel
  data/interim/des_long.parquet               full-fidelity long table (36 crops)
  data/manifests/des_ingest.json              provenance + what was removed

SCOPE (fixed by the owner): Telangana, kharif, 2014-15 to 2022-23, four crops -
Cotton (lint), Arhar/Tur, Moong (green gram), Rice.  The source file carries 36
kharif crop groups; the other 32 are unnecessary for this project and are
removed here, along with the constant State column, the redundant Year column,
the always-Kharif session column, and the 3-level MultiIndex header.

NORMALISATION (units and metrics):
  * Units are read from the source column labels, never assumed.  Cotton is in
    bales, the rest in tonnes; area is hectares for every crop.  No conversion
    is applied - a bale-to-tonne factor would be an assumption, not a cited
    value in this file.
  * `yield_reported` is the value as published: the DES reports yield rounded to
    two decimals.  `yield` is the unrounded production / area and is the
    modelling target, because 2 dp is a coarse grid for moong (a 0.01 step on a
    median of 0.63 is 1.6%, the same order as the effects being measured).
  * A hard gate asserts yield == round(yield_reported, 2) on every kept row.  If
    that identity ever fails the build stops: that is a data error, not rounding.

Authority: README section 3 (the delivered dataset) and section 4 (the identity gate).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

KEY_COLS = ("State", "District", "Year")
EXPECTED_SHAPE = (238, 111)   # verified against the delivered file 

METRIC_MAP = {
    "Area (Hectare)": "area_ha",
    "Production (Tonnes)": "production",
    "Production (Bales)": "production",
    "Yield (Tonne/Hectare)": "yield_reported",
    "Yield (Bales/Hectare)": "yield_reported",
}

MIN_AREA_HA = 10.0   # DES convention for non-commercial plots


def parse_number(raw) -> float:
    """DES cells arrive as '34,731.00', '-', '' or 'NA'.  NaN marks unparseable."""
    if raw is None:
        return float("nan")
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "NA", "N/A", "null", "None", "--"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def main() -> None:
    cfg.check_determinism()
    log(f"Step 01: DES preprocess (DATA_VERSION {cfg.data_version()})")

    # -- copy the immutable source and checksum it ---------------------------
    if not cfg.DES_RAW_COPY.exists():
        shutil.copy2(cfg.DES_SOURCE, cfg.DES_RAW_COPY)
    digest = cfg.sha256_file(cfg.DES_RAW_COPY)
    checksums = cfg.MANIFESTS / "checksums.sha256"
    line = f"{digest}  data/raw/des/{cfg.DES_RAW_COPY.name}\n"
    existing = checksums.read_text() if checksums.exists() else ""
    if line not in existing:
        with open(checksums, "a") as fh:
            fh.write(line)

    # -- parse (read_html, never read_excel) ---------------------------------
    tables = pd.read_html(cfg.DES_SOURCE)
    assert len(tables) == 1, f"expected exactly 1 table, found {len(tables)}"
    raw = tables[0]
    log(f"  source shape {raw.shape}")
    if raw.shape != EXPECTED_SHAPE:
        log(f"  WARNING: shape {raw.shape} != expected {EXPECTED_SHAPE} ")
    assert raw.columns.nlevels == 3, "expected a 3-level MultiIndex"

    key_idx = [i for i, v in enumerate(raw.columns) if v[0] in KEY_COLS]
    meta = raw.iloc[:, key_idx].copy()
    meta.columns = ["state", "district_raw", "season_raw"]

    all_crops: list[str] = []
    for crop, session, metric in raw.columns:
        if crop in KEY_COLS:
            continue
        if crop not in all_crops:
            all_crops.append(crop)
        if metric not in METRIC_MAP:
            raise KeyError(f"unmapped metric label: {metric!r}")
    log(f"  crop groups in the file: {len(all_crops)}")

    # -- reshape wide -> long ------------------------------------------------
    parts = []
    for crop in all_crops:
        block = pd.DataFrame(index=meta.index)
        seen_fields = set()
        for c in raw.columns:
            if c[0] != crop:
                continue
            field = METRIC_MAP[c[2]]
            block[field] = [parse_number(v) for v in raw[(crop, c[1], c[2])].to_numpy()]
            seen_fields.add(field)
        if seen_fields != {"area_ha", "production", "yield_reported"}:
            raise ValueError(f"{crop}: unexpected metric set {seen_fields}")
        block["crop"] = crop
        parts.append(pd.concat([meta, block], axis=1))
    full = pd.concat(parts, ignore_index=True)

    full["season"] = full["season_raw"].map(
        lambda s: cfg.season_label(cfg.season_to_year_start(str(s)))
    )
    full["year"] = full["season"].map(cfg.season_to_year_start)
    full["district_slug"] = (
        full["district_raw"].astype("string").str.strip()
        .str.replace(r"^\d+\.\s*", "", regex=True).str.lower()
    )
    full["district"] = (
        full["district_slug"].str.replace(r"^(.+)$", lambda m: m.group(1).title(), regex=True)
    )

    n0 = len(full)

    # -- scope: the four crops the project is about ---------------------------
    out_of_scope = sorted(set(full["crop"]) - set(cfg.TARGET_CROPS))
    full = full[full["crop"].isin(cfg.TARGET_CROPS)].copy()
    log(f"  crop scope: kept {len(cfg.TARGET_CROPS)}, "
        f"dropped {len(out_of_scope)} out-of-scope crop groups")

    # -- quality filter ---------------------------------------------------------
    crop_key = full["crop"].copy()
    m_area0 = full["area_ha"].eq(0)
    m_prod0 = full["production"].eq(0)
    m_small = full["area_ha"] < MIN_AREA_HA
    m_nan = full["yield_reported"].isna() | full["area_ha"].isna() | full["production"].isna()
    drop = m_area0 | m_prod0 | m_small | m_nan
    drop_log = full.loc[drop, ["district_slug", "season", "crop", "area_ha"]].copy()
    full = full[~drop].copy().reset_index(drop=True)
    log(f"  rows {len(full)} kept, {int(drop.sum())} dropped on the area/quality rules")

    # -- normalise: exact yield, units, era ----------------------------------
    full["area_unit"] = cfg.AREA_UNIT
    full["yield"] = (full["production"] / full["area_ha"]).astype("float64")
    full["era"] = full["season"].map(cfg.season_era)
    full["district_id"] = full["district_slug"] + "__" + full["era"]
    units = pd.DataFrame(cfg.CROP_UNITS).T
    full = full.join(units, on="crop")

    # -- hard gate: the published yield is production/area rounded to 2 dp ----
    recomputed = (full["production"] / full["area_ha"]).round(2)
    mismatch = (recomputed - full["yield_reported"]).abs() > 1e-9
    if mismatch.any():
        bad = full.loc[mismatch, ["district_slug", "season", "crop",
                                  "area_ha", "production", "yield_reported"]]
        raise SystemExit(
            "FATAL: published yield is not round(production/area, 2) for "
            f"{int(mismatch.sum())} row(s) - this is a data error, not rounding:\n"
            f"{bad.to_string(index=False)}"
        )
    log(f"  identity gate passed: yield == round(yield_reported, 2) on all {len(full)} rows")

    # -- order, types, rounding ---------------------------------------------
    cols = [
        "season", "year", "district", "district_slug", "era", "crop",
        "area_ha", "area_unit", "production", "production_unit",
        "yield", "yield_reported", "yield_unit",
    ]
    clean = full[cols].copy()
    clean = clean.sort_values(["era", "district_slug", "season", "crop"],
                              kind="mergesort").reset_index(drop=True)
    clean["area_ha"] = clean["area_ha"].astype("float64").round(4)
    clean["production"] = clean["production"].astype("float64").round(4)
    clean["yield"] = clean["yield"].astype("float64").round(8)
    clean["yield_reported"] = clean["yield_reported"].astype("float64").round(2)

    parquet_path = cfg.PROCESSED / "crops_kharif_clean.parquet"
    clean.to_parquet(parquet_path, index=False)
    csv_path = cfg.PROCESSED / "crops_kharif_clean.csv"
    clean.to_csv(csv_path, index=False)
    log(f"  wrote {parquet_path.name} and {csv_path.name}: "
        f"{len(clean)} rows x {clean.shape[1]} columns")

    # -- gate reporting -------------------------------------------------------
    print("\n  --- cleaned dataset by crop ---")
    summary = (
        clean.groupby("crop")
        .agg(rows=("yield", "size"), unit=("yield_unit", "first"),
             y_min=("yield", "min"), y_median=("yield", "median"),
             y_max=("yield", "max"))
        .reindex(cfg.TARGET_CROPS)
    )
    print(summary.round(3).to_string())

    print("\n  --- cleaned dataset by season ---")
    print(clean.groupby(["season", "era"]).agg(
        rows=("yield", "size"), districts=("district_slug", "nunique")).to_string())

    print("\n  --- rows removed by the quality rules ---")
    if len(drop_log):
        print(drop_log.to_string(index=False))
    else:
        print("  (none)")

    assert not clean.isna().any().any(), "NaN survived into the cleaned dataset"
    assert set(clean["crop"]) == set(cfg.TARGET_CROPS)
    assert clean["yield_unit"].notna().all()

    # -- full-fidelity long table (all 36 crops, kept for provenance) --------
    keep_full = [
        "district_raw", "district_slug", "district", "season", "year",
        "crop", "area_ha", "production", "yield_reported", "state", "era",
    ]
    full_out = full[keep_full].copy()
    full_out["session"] = "Kharif"
    interim_path = cfg.INTERIM / "des_long.parquet"
    full_out.sort_values(["district_slug", "season", "crop"],
                         kind="mergesort").to_parquet(interim_path, index=False)
    log(f"  wrote {interim_path.name} ({len(full_out)} rows, 4 crops)")

    # -- metadata ------------------------------------------------------------
    cfg.write_json(
        cfg.PROCESSED / "crops_kharif_clean.metadata.json",
        {
            "artifact": "crops_kharif_clean",
            "data_version": cfg.data_version(),
            "created_utc": cfg.utc_now_iso(),
            "scope": {
                "state": "Telangana",
                "season": "Kharif",
                "crops": cfg.TARGET_CROPS,
                "season_range": [clean["season"].min(), clean["season"].max()],
                "districts": int(clean["district_slug"].nunique()),
            },
            "rows": int(len(clean)),
            "columns": clean.columns.tolist(),
            "units": cfg.CROP_UNITS | {"area": cfg.AREA_UNIT},
            "unit_policy": (
                "Units are read from the source column labels and are never "
                "assumed. Cotton is reported in bales, the other three crops in "
                "tonnes, and area is hectares throughout. No conversion is "
                "applied: a bale-to-tonne factor would be an assumption, not a "
                "cited value in this file, and cotton is modelled on the bales "
                "scale. Cross-crop comparability comes from percentage effects, "
                "never from a converted scale."
            ),
            "yield_precision": (
                "yield = production / area_ha at full precision is the modelling "
                "target; yield_reported is the value as published (the DES rounds "
                "yield to 2 dp). 2 dp is a coarse grid for moong - a 0.01 step on "
                "a median of 0.63 t/ha is 1.6%, the same order as the effects "
                "being measured. A hard gate asserts "
                "yield == round(yield_reported, 2) on every row."
            ),
            "identity_gate": "passed",
            "source_file": str(cfg.DES_SOURCE.relative_to(cfg.ROOT)),
            "source_sha256": digest,
            "source_shape": list(raw.shape),
            "rows_in_source_long": int(n0),
            "removed": {
                "out_of_scope_crop_groups": out_of_scope,
                "out_of_scope_rows": int(n0 - len(full) - int(drop.sum())),
                "quality_rule_rows": int(drop.sum()),
                "columns_dropped": ["State", "Year (kept as season/year)",
                                    "session (Kharif-only scope)"],
            },
            "quality_rules": {
                "area_zero": int(m_area0.sum()),
                "production_zero": int(m_prod0.sum()),
                f"area_lt_{int(MIN_AREA_HA)}ha": int(m_small.sum()),
                "missing_value": int(m_nan.sum()),
                "min_area_ha": MIN_AREA_HA,
            },
            "dropped_rows": [
                {
                    "district": r["district_slug"],
                    "season": r["season"],
                    "crop": r["crop"],
                    "area_ha": None if pd.isna(r["area_ha"]) else float(r["area_ha"]),
                    "reason": "missing value" if pd.isna(r["area_ha"])
                    else f"area < {int(MIN_AREA_HA)} ha",
                }
                for _, r in drop_log.iterrows()
            ],
            "primary_panel_rows": int(
                clean[clean["era"] == "post2016"].shape[0]
            ),
            "sha256_parquet": cfg.sha256_file(parquet_path),
            "sha256_csv": cfg.sha256_file(csv_path),
        },
    )

    cfg.write_json(
        cfg.MANIFESTS / "des_ingest.json",
        {
            "artifact": "crops_kharif_clean",
            "created_utc": cfg.utc_now_iso(),
            "yield_source": "DES district-wise kharif crop production "
            "(Directorate of Economics & Statistics, Govt. of India)",
            "source_file": str(cfg.DES_SOURCE.relative_to(cfg.ROOT)),
            "raw_copy": str(cfg.DES_RAW_COPY.relative_to(cfg.ROOT)),
            "yield_file_sha256": digest,
            "parser": "pandas.read_html (file is HTML despite the .xls extension)",
            "parsed_shape": list(raw.shape),
            "crop_groups_in_file": all_crops,
            "crops_in_scope": cfg.TARGET_CROPS,
            "rows_out": int(len(clean)),
            "rows_dropped_quality": int(drop.sum()),
            "seasons": sorted(clean["season"].unique().tolist()),
            "districts": sorted(clean["district_slug"].unique().tolist()),
            "sha256": cfg.sha256_file(parquet_path),
        },
    )
    log("  wrote data/processed/crops_kharif_clean.metadata.json")
    log("  wrote data/manifests/des_ingest.json")


if __name__ == "__main__":
    main()