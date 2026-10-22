"""Step 03 - Ingest ERA5 daily weather for the 32 district centroids.

Source : Open-Meteo historical archive API (ERA5 reanalysis), no API key.
Endpoint: https://archive-api.open-meteo.com/v1/archive

Transport: curl with a mandatory retry harness (common.fetch).  urllib fails
through this network path; the archive endpoint intermittently drops the TLS
connection with SSL_ERROR_SYSCALL, so every request is retried with a 5 s
pause (60 s on HTTP 429).

Outputs:
  data/raw/openmeteo/era5_<window>_<hash>.json   cached raw responses (immutable)
  data/interim/weather_daily.parquet              district_slug x date
  data/manifests/weather_fetch.json                per-fetch provenance

Authority: plan/SRS.md §3.2, §5.1 ; plan/GUIDE.md Step 4.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

log = C.log
C.ensure_dirs()

DAILY_VARS = [
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
    "vapour_pressure_deficit_max",
    "shortwave_radiation_sum",
]

# API variable name -> column name in the interim parquet
LOCAL_COL = {
    "precipitation_sum": "precip_mm",
    "temperature_2m_max": "tmax_c",
    "temperature_2m_min": "tmin_c",
    "vapour_pressure_deficit_max": "vpd_max_kpa",
    "shortwave_radiation_sum": "srad_mj",
}

BATCH_SIZE = 8          # districts per request (keeps each response ~1 MB)
# The archive API does not echo the requested coordinate back verbatim: it
# resolves it to the surrounding ERA5 grid node, which can sit up to half a
# grid cell away (0.125 deg).  The check below exists to catch a *misaligned
# district-to-block mapping*, not to police grid snapping, so the tolerance is
# half a cell.  Adjacent districts (Warangal / Warangal Urban) are ~0.27 deg
# apart, so this tolerance cannot mask a genuine off-by-one shift.
COORD_TOLERANCE_DEG = 0.15


def build_url(lats: list[float], lons: list[float], start: str, end: str) -> str:
    return (
        f"{C.OPEN_METEO_ARCHIVE}"
        f"?latitude={','.join(f'{v:.4f}' for v in lats)}"
        f"&longitude={','.join(f'{v:.4f}' for v in lons)}"
        f"&start_date={start}&end_date={end}"
        f"&daily={','.join(DAILY_VARS)}"
        f"&timezone=GMT"
    )


def fetch_window(
    coords: list[tuple[str, float, float]],
    start: str,
    end: str,
    tag: str,
    batch_size: int = BATCH_SIZE,
) -> tuple[list[dict], list[dict]]:
    """Fetch one window in batches.  Returns (records, manifest_entries)."""
    records: list[dict] = []
    entries: list[dict] = []

    for i in range(0, len(coords), batch_size):
        batch = coords[i : i + batch_size]
        lats = [c[1] for c in batch]
        lons = [c[2] for c in batch]
        url = build_url(lats, lons, start, end)
        key = hashlib.sha1(url.encode()).hexdigest()[:12]
        cache = C.RAW_OPENMETEO / f"era5_{tag}_{start[:4]}_{key}.json"

        if cache.exists():
            log(f"  [{tag}] batch {i//batch_size + 1}: cache hit {cache.name}")
            payload = C.read_json(cache)
        else:
            log(
                f"  [{tag}] batch {i//batch_size + 1}/"
                f"{-(-len(coords)//batch_size)}: {len(batch)} coords, "
                f"{start}..{end}"
            )
            payload = C.fetch(url, tries=8, timeout=120)
            cache.write_text(
                json.dumps(payload, separators=(",", ":"), sort_keys=True)
            )

        # --- gate G4.4: one block per requested coordinate, in order --------
        if not isinstance(payload, list):
            raise SystemExit(f"FATAL: expected a list of blocks, got {type(payload)}")
        if len(payload) != len(batch):
            raise SystemExit(
                f"FATAL: requested {len(batch)} coordinates, received {len(payload)} "
                "blocks - refusing to proceed (silent misalignment)"
            )

        max_dev = 0.0
        seen_points: dict[tuple[float, float], str] = {}
        for (slug, lat, lon), block in zip(batch, payload):
            rlat, rlon = float(block["latitude"]), float(block["longitude"])
            dev = max(abs(rlat - lat), abs(rlon - lon))
            max_dev = max(max_dev, dev)
            if dev > COORD_TOLERANCE_DEG:
                raise SystemExit(
                    f"FATAL: coordinate mismatch for {slug}: requested "
                    f"({lat},{lon}) got ({rlat},{rlon}) - deviation {dev:.4f} deg"
                )
            key = (round(rlat, 3), round(rlon, 3))
            if key in seen_points:
                log(
                    f"  WARNING: {slug} and {seen_points[key]} resolved to the same "
                    f"ERA5 grid node {key} - both districts read identical weather"
                )
            else:
                seen_points[key] = slug
            daily = block["daily"]
            dates = daily["time"]
            frame = pd.DataFrame(
                {
                    "district_slug": slug,
                    "date": dates,
                    "precip_mm": daily["precipitation_sum"],
                    "tmax_c": daily["temperature_2m_max"],
                    "tmin_c": daily["temperature_2m_min"],
                    "vpd_max_kpa": daily["vapour_pressure_deficit_max"],
                    "srad_mj": daily["shortwave_radiation_sum"],
                }
            )
            frame["grid_lat"] = rlat
            frame["grid_lon"] = rlon
            frame["elevation_m"] = block.get("elevation")
            records.append(frame)

        entries.append(
            {
                "window": tag,
                "start_date": start,
                "end_date": end,
                "url": url,
                "raw_file": str(cache.relative_to(C.ROOT)),
                "sha256": C.sha256_file(cache),
                "fetched_utc": C.utc_now_iso(),
                "n_coordinates": len(batch),
                "n_blocks_returned": len(payload),
                "n_days": len(payload[0]["daily"]["time"]) if payload else 0,
                "max_coordinate_deviation_deg": round(max_dev, 4),
                "bytes": cache.stat().st_size,
            }
        )

    return records, entries


def main() -> None:
    C.check_determinism()
    log("Step 03: ERA5 ingest")

    districts = pd.read_csv(C.GEO / "districts.csv")
    # one coordinate pair per district slug (the era rows repeat the same point)
    coords_df = (
        districts.sort_values("district_id")
        .drop_duplicates(subset="district_slug")[["district_slug", "lat", "lon"]]
        .sort_values("district_slug")
        .reset_index(drop=True)
    )
    coords = [
        (r.district_slug, float(r.lat), float(r.lon)) for r in coords_df.itertuples()
    ]
    log(f"  {len(coords)} district centroids")

    frames: list[dict] = []
    entries: list[dict] = []

    windows = {
        "analysis": (C.INGEST_START, C.INGEST_END, BATCH_SIZE),
        # The 2026 marker needs one rainfall reading per district.  The archive
        # API enforces an hourly request quota, so the marker is pulled in a
        # single multi-coordinate request rather than four.
        "marker2026": (C.MARKER_START, C.MARKER_END, len(coords)),
    }
    wanted = sys.argv[1] if len(sys.argv) > 1 else "all"
    for tag, (start, end, bsize) in windows.items():
        if wanted not in ("all", tag):
            continue
        recs, ents = fetch_window(coords, start, end, tag, batch_size=bsize)
        frames.extend(recs)
        entries.extend(ents)

    weather = pd.concat(frames, ignore_index=True)
    weather["date"] = pd.to_datetime(weather["date"])

    # Merge with any previously fetched window so the two windows can be
    # pulled independently (the archive API enforces an hourly quota).
    out = C.INTERIM / "weather_daily.parquet"
    if out.exists():
        prev = pd.read_parquet(out)
        prev["date"] = pd.to_datetime(prev["date"])
        weather = pd.concat([prev, weather], ignore_index=True)
    weather = (
        weather.drop_duplicates(subset=["district_slug", "date"], keep="last")
        .sort_values(["district_slug", "date"])
        .reset_index(drop=True)
    )

    # --- gate G4.2 / G4.5 ---------------------------------------------------
    expected_days = (pd.Timestamp(C.INGEST_END) - pd.Timestamp(C.INGEST_START)).days + 1
    marker_days = (pd.Timestamp(C.MARKER_END) - pd.Timestamp(C.MARKER_START)).days + 1
    n_main = int((weather["date"] <= pd.Timestamp(C.INGEST_END)).sum())
    expected_main = expected_days * len(coords)
    assert n_main == expected_main, (
        f"row count {n_main} != expected {expected_main} "
        f"({len(coords)} districts x {expected_days} days)"
    )
    n_marker = int((weather["date"] >= pd.Timestamp(C.MARKER_START)).sum())
    if n_marker:
        assert n_marker == marker_days * len(coords), "2026 marker row count mismatch"
    else:
        log("  2026 marker window not present in this run")

    for slug, g in weather[weather["date"] <= pd.Timestamp(C.INGEST_END)].groupby(
        "district_slug"
    ):
        g = g.sort_values("date")
        full = pd.date_range(g["date"].min(), g["date"].max(), freq="D")
        assert len(g) == len(full), f"{slug}: non-contiguous date series"
        assert (g["date"].diff().dt.days.dropna() == 1).all(), f"{slug}: date gap"

    nan_rate = (
        weather[[LOCAL_COL[v] for v in DAILY_VARS]].isna().mean().round(6).to_dict()
    )
    log(f"  rows {len(weather)}  NaN rate {nan_rate}")

    for col in LOCAL_COL.values():
        weather[col] = weather[col].astype("float64").round(4)

    weather.to_parquet(out, index=False)
    log(f"  wrote {out} rows={len(weather)}")

    # district-year rainfall totals for a quick sanity read
    w = weather[weather["date"] <= pd.Timestamp(C.INGEST_END)].copy()
    w["year"] = w["date"].dt.year
    w["season_year"] = w["date"].dt.year.where(w["date"].dt.month >= 6, w["date"].dt.year - 1)
    annual = w.groupby("season_year")["precip_mm"].sum()
    log("  state-mean annual precipitation (mm), all districts:")
    for yr, val in annual.items():
        log(f"    {yr}: {val/len(coords):.0f}")

    C.write_json(
        C.MANIFESTS / "weather_fetch.json",
        {
            "artifact": "weather_daily.parquet",
            "created_utc": C.utc_now_iso(),
            "weather_source": "open-meteo/era5",
            "weather_endpoint": C.OPEN_METEO_ARCHIVE,
            "weather_licence": C.WEATHER_LICENCE,
            "daily_variables": DAILY_VARS,
            "temp_window": [C.INGEST_START, C.INGEST_END],
            "marker_window": [C.MARKER_START, C.MARKER_END],
            "analysis_window": ["06-01", "09-30"],
            "districts": len(coords),
            "batch_size": BATCH_SIZE,
            "rows": int(len(weather)),
            "rows_analysis_window": int(n_main),
            "rows_marker_window": int(n_marker),
            "nan_rate": nan_rate,
            "fetches": entries,
            "sha256": C.sha256_file(out),
        },
    )
    log("  manifest written: data/manifests/weather_fetch.json")


if __name__ == "__main__":
    main()
