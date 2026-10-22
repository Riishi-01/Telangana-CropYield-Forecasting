"""Step 01 - Ingest the DES district-wise kharif crop production file.

Input : data/horizontal_crop_vertical_year_report.xls
        (an HTML document despite the .xls extension - parsed with read_html)
Output: data/interim/des_long.parquet
        one row per district x season x crop with area / production / yield
        plus the unit implied by the source column label.

Authority: plan/SRS.md §3.1, §3.3, §5.3 ; plan/GUIDE.md Step 3.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

log = C.log
C.ensure_dirs()

# --------------------------------------------------------------------------- #
# Metric label -> canonical field + unit.  The unit is read from the source
# column label, never assumed (SRS §5.3: cotton is in bales, not tonnes).
# --------------------------------------------------------------------------- #
METRIC_MAP = {
    "Area (Hectare)": ("area_ha", "ha"),
    "Production (Tonnes)": ("production", "t"),
    "Production (Bales)": ("production", "bales"),
    "Yield (Tonne/Hectare)": ("yield", "t/ha"),
    "Yield (Bales/Hectare)": ("yield", "bales/ha"),
}

EXPECTED_SHAPE = (238, 111)  # verified against the delivered file (ERRATA C2)
KEY_COLS = ("State", "District", "Year")


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
    C.check_determinism()
    log("Step 01: DES ingest")

    # -- 3.1 copy the immutable source into data/raw/des/ and checksum it ----
    if not C.DES_RAW_COPY.exists():
        shutil.copy2(C.DES_SOURCE, C.DES_RAW_COPY)
    digest = C.sha256_file(C.DES_RAW_COPY)
    checksums = C.MANIFESTS / "checksums.sha256"
    line = f"{digest}  data/raw/des/{C.DES_RAW_COPY.name}\n"
    existing = checksums.read_text() if checksums.exists() else ""
    if line not in existing:
        with open(checksums, "a") as fh:
            fh.write(line)
    log(f"  raw copy sha256 {digest[:16]}...")

    # -- 3.2 parse (read_html, never read_excel) -----------------------------
    tables = pd.read_html(C.DES_SOURCE)
    assert len(tables) == 1, f"expected exactly 1 table, found {len(tables)}"
    df = tables[0]
    log(f"  parsed shape {df.shape}")
    if df.shape != EXPECTED_SHAPE:
        log(f"  WARNING: shape {df.shape} != expected {EXPECTED_SHAPE} (ERRATA C2)")
    assert df.columns.nlevels == 3, "expected a 3-level MultiIndex"

    # -- 3.3 reshape wide -> long --------------------------------------------
    meta = df.iloc[:, :3].copy()
    meta.columns = ["state", "district_raw", "season_raw"]
    meta = meta.reset_index(drop=True)

    groups: dict[str, dict[str, tuple[str, str, str]]] = {}
    for crop, session, metric in df.columns:
        if crop in KEY_COLS:
            continue
        if metric not in METRIC_MAP:
            raise KeyError(f"unmapped metric label: {metric!r}")
        field, unit = METRIC_MAP[metric]
        groups.setdefault(crop, {})[field] = (session, metric, unit)

    parts = []
    for crop, fields in groups.items():
        session = fields["area_ha"][0]
        block = pd.DataFrame(index=meta.index)
        for field in ("area_ha", "production", "yield"):
            _, metric, unit = fields[field]
            block[field] = [parse_number(v) for v in df[(crop, session, metric)].to_numpy()]
        block["crop"] = crop
        block["session"] = session
        block["unit"] = fields["yield"][2]  # yield unit == production unit per group
        parts.append(pd.concat([meta, block], axis=1))

    df_long = pd.concat(parts, ignore_index=True)

    # crop -> unit for EVERY group in the file, including the groups the QC
    # filter later removes entirely (e.g. Mesta, which is in bales and is
    # dropped on area).  This is what the manifest records.
    file_units = {crop: fields["yield"][2] for crop, fields in groups.items()}

    # district / season keys
    df_long["district_raw"] = df_long["district_raw"].astype("string").str.strip()
    df_long["season"] = (
        df_long["season_raw"]
        .astype("string")
        .str.strip()
        .str.replace(" ", "", regex=False)
    )
    df_long["year_start"] = df_long["season"].map(C.season_to_year_start)
    df_long["season"] = df_long["year_start"].map(C.season_label)
    df_long["district_slug"] = (
        df_long["district_raw"].str.replace(r"^\d+\.\s*", "", regex=True).str.lower()
    )
    df_long["state"] = df_long["state"].astype("string").str.strip()

    keep = [
        "state",
        "district_raw",
        "district_slug",
        "season",
        "year_start",
        "crop",
        "session",
        "unit",
        "area_ha",
        "production",
        "yield",
    ]
    df_long = df_long[keep]

    # -- 3.4 quality filter (GUIDE Step 3.4) --------------------------------
    n0 = len(df_long)
    crop_key = df_long["crop"].copy()
    mask_area0 = df_long["area_ha"].eq(0)
    mask_prod0 = df_long["production"].eq(0)
    mask_small = df_long["area_ha"] < 10
    mask_nan = df_long["yield"].isna()
    drop = mask_area0 | mask_prod0 | mask_small | mask_nan
    df_long = df_long[~drop].copy().reset_index(drop=True)
    log(f"  rows {n0} -> {len(df_long)} (dropped {int(drop.sum())})")

    df_long["area_ha"] = df_long["area_ha"].astype("float64").round(4)
    df_long["production"] = df_long["production"].astype("float64").round(4)
    df_long["yield"] = df_long["yield"].astype("float64").round(6)

    out_path = C.INTERIM / "des_long.parquet"
    df_long.to_parquet(out_path, index=False)
    log(f"  wrote {out_path} rows={len(df_long)}")

    # -- gate reporting ------------------------------------------------------
    print("\n  --- per-crop row counts and units (gate G3.3) ---")
    counts = (
        df_long.groupby("crop")
        .agg(
            rows=("yield", "size"),
            unit=("unit", "first"),
            y_min=("yield", "min"),
            y_max=("yield", "max"),
        )
        .sort_values("rows", ascending=False)
    )
    print(counts.to_string())

    crop_key = crop_key.reindex(counts.index)
    drops = pd.DataFrame(
        {
            "area_zero": mask_area0.groupby(crop_key).sum(),
            "prod_zero": mask_prod0.groupby(crop_key).sum(),
            "area_lt_10ha": mask_small.groupby(crop_key).sum(),
            "yield_missing": mask_nan.groupby(crop_key).sum(),
        }
    )
    drops = drops.reindex(counts.index)
    print("\n  --- drop reasons per crop (gate G3.4) ---")
    print(drops[drops.sum(axis=1) > 0].to_string() if drops.sum().sum() else "  (none)")

    print("\n  --- district structure (gate G2.1) ---")
    per_year = (
        df_long[["season", "district_slug"]].drop_duplicates().groupby("season").size()
    )
    print(per_year.to_string())
    print(f"  unique districts: {df_long['district_slug'].nunique()}")
    print(f"  seasons: {sorted(df_long['season'].unique())}")

    assert not df_long["yield"].isna().any(), "NaN yield survived the filter"
    assert "bales/ha" in set(df_long["unit"]), "cotton bales/ha unit missing"
    assert (df_long["district_slug"] == "").sum() == 0, "empty district slug"

    # -- manifest ------------------------------------------------------------
    C.write_json(
        C.MANIFESTS / "des_ingest.json",
        {
            "artifact": "des_long.parquet",
            "created_utc": C.utc_now_iso(),
            "yield_source": "DES district-wise season-wise crop production (Govt. of India)",
            "source_file": str(C.DES_SOURCE.relative_to(C.ROOT)),
            "raw_copy": str(C.DES_RAW_COPY.relative_to(C.ROOT)),
            "yield_file_sha256": digest,
            "parser": "pandas.read_html (file is HTML despite the .xls extension)",
            "parsed_shape": list(df.shape),
            "rows_in": int(n0),
            "rows_out": int(len(df_long)),
            "rows_dropped": int(drop.sum()),
            "drop_reasons_total": {
                "area_zero": int(mask_area0.sum()),
                "production_zero": int(mask_prod0.sum()),
                "area_lt_10ha": int(mask_small.sum()),
                "yield_missing": int(mask_nan.sum()),
            },
            "districts": sorted(df_long["district_slug"].unique().tolist()),
            "seasons": sorted(df_long["season"].unique().tolist()),
            "crops": sorted(df_long["crop"].unique().tolist()),
            "crops_in_file": sorted(file_units.keys()),
            "units_in_file": {k: v for k, v in sorted(file_units.items())},
            "per_crop_rows": {k: int(v) for k, v in counts["rows"].items()},
            "per_crop_unit": {k: v for k, v in counts["unit"].items()},
            "sha256": C.sha256_file(out_path),
        },
    )
    log("  manifest written: data/manifests/des_ingest.json")


if __name__ == "__main__":
    main()
