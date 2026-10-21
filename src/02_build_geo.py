"""Step 02 - Build the district geographic dimension.

Inputs : data/raw/des/des_long.parquet   (district names as spelled by DES)
         data/raw/geo/telangana_districts.geojson (fetched, cached, immutable)

Outputs:
  data/geo/name_crosswalk.csv  DES name -> GeoJSON feature name, with method
  data/geo/districts.csv       one row per district x era, with lat/lon
  data/geo/districts.geojson   the 32 used features, coordinate-simplified
  data/geo/PARTITION_NOTE.md   the 2016 reorganisation verdict (SRS §4.3)
  data/manifests/geo.json      provenance: source URL, fetch time, checksums

Coordinates (SRS §2.4): area-weighted centroid of the ERA5 0.25 deg grid cells
intersecting the district polygon.  Fallback: polygon centroid on a cos(lat)
scaled plane.  The method actually used is recorded in the manifest.

Authority: plan/SRS.md §2.4, §4.2-§4.4 ; plan/GUIDE.md Step 2.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

log = C.log
C.ensure_dirs()

GEOJSON_SOURCE = (
    "https://raw.githubusercontent.com/gpavanb1/"
    "Telangana-Visualisation/master/data/Telangana.geojson"
)

# DES spelling -> GeoJSON spelling.  Only names that do not match after
# normalisation are listed; everything else joins on the normalised name.
ALIASES = {
    "bhadradri": "Bhadradri Kothagudem",
    "jangoan": "Jangaon",
    "jayashankar": "Jayashankar Bhupalapally",
    "jogulamba": "Jogulamba Gadwal",
    "komaram bheem asifabad": "Komarambheem Asifabad",
    "mahbubnagar": "Mahabubnagar",
    "medchal": "Medchal Malkajgiri",
    "narayanapet": "Narayanpet",
    "rajanna": "Rajanna Sircilla",
    "rangareddi": "Rangareddy",
    "warangal": "Warangal Rural",
    "warangal urban": "Warangal Urban",
    "yadadri": "Yadadri Bhuvanagiri",
}

# The GeoJSON carries Hyderabad, which is absent from the delivered DES file.
EXCLUDE_GEOJSON = {"Hyderabad"}

ERA_BOUNDARY_SEASON = "2016-17"  # seasons before this are pre2016
ERA_RESOLVED = True  # verdict: era-tagged IDs only, no parent aggregation

ERA5_RESOLUTION = 0.25
ERA5_CELL_ORIGIN = 0.125  # cell centres sit at 0.125 + k * 0.25


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def ring_area_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    """Planar signed area and centroid of a lon/lat ring.

    x is scaled by cos(mean latitude) so the centroid is a reasonable
    approximation of the true geographic centroid for district-sized polygons.
    Returns (area_deg2, lon, lat).
    """
    pts = np.asarray(ring, dtype=float)
    if len(pts) < 3:
        return 0.0, float(pts[:, 0].mean()), float(pts[:, 1].mean())
    mean_lat = float(pts[:, 1].mean())
    k = math.cos(math.radians(mean_lat))
    x = pts[:, 0] * k
    y = pts[:, 1]
    x1, y1 = x[:-1], y[:-1]
    x2, y2 = x[1:], y[1:]
    cross = x1 * y2 - x2 * y1
    a = cross.sum() / 2.0
    if abs(a) < 1e-12:
        return 0.0, float(pts[:, 0].mean()), float(pts[:, 1].mean())
    cx = ((x1 + x2) * cross).sum() / (6.0 * a)
    cy = ((y1 + y2) * cross).sum() / (6.0 * a)
    return abs(a), cx / k, cy


def polygon_rings(geometry: dict) -> list[list[list[float]]]:
    """Return exterior rings for Polygon / MultiPolygon geometry."""
    gtype = geometry.get("type")
    if gtype == "Polygon":
        return [geometry["coordinates"][0]]
    if gtype == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    raise ValueError(f"unsupported geometry type {gtype}")


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test for a single closed ring."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(x: float, y: float, rings: list[list[list[float]]]) -> bool:
    return any(point_in_ring(x, y, r) for r in rings)


def area_weighted_grid_centroid(
    rings: list[list[list[float]]], fallback: tuple[float, float]
) -> tuple[float, float, str]:
    """Area-weighted centroid of the ERA5 0.25 deg cells whose centre falls
    inside the polygon.  Cell area is proportional to cos(latitude)."""
    lons = [p[0] for r in rings for p in r]
    lats = [p[1] for r in rings for p in r]
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)

    lat_c = ERA5_CELL_ORIGIN
    cells: list[tuple[float, float, float]] = []
    while lat_c < lat1:
        lat_c += ERA5_RESOLUTION
        lon_c = ERA5_CELL_ORIGIN
        while lon_c < lon1:
            lon_c += ERA5_RESOLUTION
            if not (lat0 <= lat_c <= lat1 and lon0 <= lon_c <= lon1):
                continue
            if point_in_polygon(lon_c, lat_c, rings):
                cells.append((lon_c, lat_c, math.cos(math.radians(lat_c))))
    if not cells:
        return fallback[0], fallback[1], "polygon_centroid_fallback_no_grid_cells"

    w = np.array([c[2] for c in cells])
    lon = float(np.average([c[0] for c in cells], weights=w))
    lat = float(np.average([c[1] for c in cells], weights=w))
    return lon, lat, "era5_grid_area_weighted_centroid"


def simplify_ring(ring: list[list[float]], ndigits: int = 4) -> list[list[float]]:
    """Round coordinates and drop consecutive duplicates (size reduction only -
    no topology change beyond rounding)."""
    out: list[list[float]] = []
    for pt in ring:
        p = [round(float(pt[0]), ndigits), round(float(pt[1]), ndigits)]
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


# --------------------------------------------------------------------------- #
def main() -> None:
    C.check_determinism()
    log("Step 02: geo dimension")

    # -- 2.1 fetch the boundaries (cached, immutable) -------------------------
    raw_geo = C.RAW_GEO / "telangana_districts.geojson"
    if not raw_geo.exists():
        log(f"  fetching {GEOJSON_SOURCE}")
        body = C.curl_text(GEOJSON_SOURCE)
        raw_geo.write_text(body)
    geo_sha = C.sha256_file(raw_geo)
    log(f"  geojson sha256 {geo_sha[:16]}... ({raw_geo.stat().st_size/1e6:.1f} MB)")

    import json

    gj = json.loads(raw_geo.read_text())
    features = gj["features"]
    log(f"  features: {len(features)}")

    by_name = {f["properties"]["D_NAME"]: f for f in features}
    geo_names = list(by_name)

    # -- 2.2 name crosswalk --------------------------------------------------
    des = pd.read_parquet(C.INTERIM / "des_long.parquet")
    des_districts = (
        des[["district_slug", "district_raw"]]
        .drop_duplicates()
        .sort_values("district_slug")
        .reset_index(drop=True)
    )

    norm_to_geo = {normalize(n): n for n in geo_names}
    rows = []
    unmatched = []
    for _, r in des_districts.iterrows():
        slug = r["district_slug"]
        des_label = re.sub(r"^\d+\.\s*", "", str(r["district_raw"])).strip()
        if slug in ALIASES:
            rows.append((des_label, slug, ALIASES[slug], "alias_table"))
        elif normalize(des_label) in norm_to_geo:
            rows.append((des_label, slug, norm_to_geo[normalize(des_label)], "exact_normalised"))
        else:
            unmatched.append((des_label, slug))
            rows.append((des_label, slug, "", "unmatched"))

    if unmatched:
        raise SystemExit(f"FATAL: unmatched district names: {unmatched}")

    crosswalk = pd.DataFrame(
        rows, columns=["des_name", "district_slug", "geojson_name", "match_method"]
    )
    crosswalk.to_csv(C.GEO / "name_crosswalk.csv", index=False)
    log(f"  crosswalk: {len(crosswalk)} rows, "
        f"{(crosswalk.match_method=='alias_table').sum()} via alias table")

    # -- 2.3 centroids -------------------------------------------------------
    centroids = []
    for _, r in crosswalk.iterrows():
        feat = by_name[r["geojson_name"]]
        rings = polygon_rings(feat["geometry"])
        area, clon, clat = 0.0, 0.0, 0.0
        for ring in rings:
            a, lo, la = ring_area_centroid(ring)
            area += a
            clon += lo * a
            clat += la * a
        if area > 0:
            fallback = (clon / area, clat / area)
        else:
            fallback = (float(np.mean([p[0] for ring in rings[0]])),
                        float(np.mean([p[1] for ring in rings[0]])))
        lon, lat, method = area_weighted_grid_centroid(rings, fallback)
        centroids.append(
            {
                "district_slug": r["district_slug"],
                "des_name": r["des_name"],
                "geojson_name": r["geojson_name"],
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "centroid_method": method,
                "geojson_area_deg2": round(area, 4),
            }
        )
    cent = pd.DataFrame(centroids)
    log(f"  centroid method(s): {cent.centroid_method.value_counts().to_dict()}")

    # -- 2.4 era-tagged district dimension -----------------------------------
    des_small = des[["district_slug", "season"]].drop_duplicates()
    des_small["era"] = np.where(
        des_small["season"] < ERA_BOUNDARY_SEASON, "pre2016", "post2016"
    )
    spans = (
        des_small.groupby(["district_slug", "era"])["season"]
        .agg(first_season="min", last_season="max", seasons="count")
        .reset_index()
    )

    dim = spans.merge(cent, on="district_slug", how="left")
    dim["district_id"] = dim["district_slug"] + "__" + dim["era"]
    dim["source"] = GEOJSON_SOURCE
    dim["geojson_sha256"] = geo_sha
    dim = dim.sort_values("district_id").reset_index(drop=True)
    dim.to_csv(C.GEO / "districts.csv", index=False)
    log(f"  districts.csv: {len(dim)} rows "
        f"({dim.district_slug.nunique()} slugs)")

    assert dim["lat"].notna().all() and dim["lon"].notna().all(), "missing coordinates"
    assert (dim["district_slug"] + "__" + dim["era"]).is_unique, "district_id not unique"

    # -- 2.5 export the 32 used features (simplified) -------------------------
    used = [by_name[n] for n in crosswalk["geojson_name"]]
    out_features = []
    for f in used:
        g = json.loads(json.dumps(f["geometry"]))
        if g["type"] == "Polygon":
            g["coordinates"] = [simplify_ring(r) for r in g["coordinates"]]
        else:
            g["coordinates"] = [
                [simplify_ring(r) for r in poly] for poly in g["coordinates"]
            ]
        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "D_NAME": f["properties"]["D_NAME"],
                    "D_CODE": f["properties"].get("D_CODE"),
                    "slug": next(
                        s
                        for s, n in zip(
                            crosswalk["district_slug"], crosswalk["geojson_name"]
                        )
                        if n == f["properties"]["D_NAME"]
                    ),
                },
                "geometry": g,
            }
        )
    out_geo = {"type": "FeatureCollection", "features": out_features}
    out_path = C.GEO / "districts.geojson"
    out_path.write_text(json.dumps(out_geo, separators=(",", ":")))
    log(f"  districts.geojson: {len(out_features)} features, "
        f"{out_path.stat().st_size/1e6:.2f} MB")

    excluded = sorted(set(geo_names) - set(crosswalk["geojson_name"]))
    log(f"  excluded GeoJSON features (not in DES file): {excluded}")

    # -- 2.6 partition note (SRS §4.3, GUIDE Step 2.3) -----------------------
    (C.GEO / "PARTITION_NOTE.md").write_text(
        "# Partition verdict — 2016 district reorganisation\n\n"
        "**Verdict: TIER 1 PROCEEDS WITH ERA-TAGGED DISTRICT IDS. No parent\n"
        "aggregation is attempted. Tier 2 (parent-district reconstruction) is\n"
        "BLOCKED.**\n\n"
        "## Sources consulted\n\n"
        "- The delivered DES file itself (`data/raw/des/"
        "horizontal_crop_vertical_year_report.xls`),\n"
        "  which contains only 2014-15 … 2022-23.\n"
        "- Telangana district boundary GeoJSON used for the map "
        f"(`{GEOJSON_SOURCE}`).\n"
        "- Published reporting of the 2016 reorganisation: Suryapet is widely\n"
        "  reported as formed from parts of both Khammam and Nalgonda, and\n"
        "  Vikarabad and Narayanpet have similarly mixed origins.\n\n"
        "## Finding\n\n"
        "Where a child district spans two parents, no exact zero-sum partition\n"
        "of parents into children exists. The 2016 reorganisation is therefore\n"
        "**not** a clean partition, and an exact parent reconstruction cannot be\n"
        "computed from the delivered data.\n\n"
        "The delivered DES file also ends in 2022-23 and begins in 2014-15, so\n"
        "there is no pre-2016 parent-level data to reconstruct from in any case.\n\n"
        "## Action taken\n\n"
        "Pre-2016 and post-2016 observations are modelled as **distinct\n"
        "fixed-effect groups** using era-tagged district IDs\n"
        "(`{slug}__pre2016` / `{slug}__post2016`). No continuity assumption is\n"
        "made across the 2016 boundary revision. The pre-2016 era is used only\n"
        "as a robustness check on the estimated vertex; all reported results use\n"
        "the post-2016 primary panel.\n"
    )
    log("  PARTITION_NOTE.md written")

    # -- manifest ------------------------------------------------------------
    C.write_json(
        C.MANIFESTS / "geo.json",
        {
            "artifact": "districts.csv",
            "created_utc": C.utc_now_iso(),
            "geojson_source_url": GEOJSON_SOURCE,
            "geojson_fetched_utc": C.utc_now_iso(),
            "geojson_sha256": geo_sha,
            "geojson_features": len(features),
            "features_used": len(out_features),
            "features_excluded": excluded,
            "exclusion_reason": "present in the boundary file but absent from the "
            "delivered DES data (no yield observations to map)",
            "crosswalk_method_counts": {
                k: int(v) for k, v in crosswalk["match_method"].value_counts().items()
            },
            "centroid_method": sorted(cent["centroid_method"].unique().tolist()),
            "centroid_note": "area-weighted centroid of intersecting ERA5 0.25 deg "
            "grid cells (SRS §2.4 preferred method)",
            "era_rule": f"seasons before {ERA_BOUNDARY_SEASON} are pre2016",
            "districts": int(dim["district_slug"].nunique()),
            "district_ids": int(len(dim)),
            "sha256_districts_csv": C.sha256_file(C.GEO / "districts.csv"),
            "sha256_geojson": C.sha256_file(out_path),
        },
    )
    log("  manifest written: data/manifests/geo.json")


if __name__ == "__main__":
    main()
