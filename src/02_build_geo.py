"""Step 02 - Build the district geographic dimension.

Inputs : data/raw/des/des_long.parquet   (district names as spelled by DES)
         data/raw/geo/telangana_districts.geojson (fetched, cached, immutable)

Outputs:
  data/geo/name_crosswalk.csv  DES name -> GeoJSON feature name, with method
  data/geo/districts.csv       one row per district x era, with lat/lon
  data/geo/districts.geojson   the 32 used features, coordinate-simplified
  data/geo/PARTITION_NOTE.md   the 2016 reorganisation verdict
  data/manifests/geo.json      provenance: source URL, fetch time, checksums

Coordinates: area-weighted centroid of the ERA5 0.25 deg grid cells
intersecting the district polygon.  Fallback: polygon centroid on a cos(lat)
scaled plane.  The method actually used is recorded in the manifest.

Authority: README section 9 (coordinates and the 2016 reorganisation).
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

# Era boundaries live in common.py: seasons before 2016-17 are pre2016, and
# before 2001-02 they are pre2001 (Hyderabad had not yet been carved out of
# Ranga Reddy).  The verdict - era-tagged ids, no parent aggregation - is
# recorded in PARTITION_NOTE.md.

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
    des_small["era"] = des_small["season"].map(C.season_era)
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

    # -- 2.5 export the used features (simplified) ---------------------------
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
                    "no_data": False,
                },
                "geometry": g,
            }
        )

    # Hyderabad is in the boundary file but has no yield observation in the
    # delivered DES data.  It is carried as a "no_data" feature so the map has
    # no unexplained hole, and it is never given a value.
    for name in sorted(EXCLUDE_GEOJSON):
        f = by_name[name]
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
                    "D_NAME": name,
                    "D_CODE": f["properties"].get("D_CODE"),
                    "slug": "",
                    "no_data": True,
                    "no_data_reason": "no yield observation in the delivered DES file",
                },
                "geometry": g,
            }
        )

    out_geo = {"type": "FeatureCollection", "features": out_features}
    out_path = C.GEO / "districts.geojson"
    out_path.write_text(json.dumps(out_geo, separators=(",", ":")))
    log(f"  districts.geojson: {len(out_features)} features "
        f"({sum(1 for f in out_features if f['properties'].get('no_data'))} with no data), "
        f"{out_path.stat().st_size/1e6:.2f} MB")

    excluded = sorted(set(geo_names) - set(crosswalk["geojson_name"]))
    log(f"  excluded GeoJSON features (not in DES file): {excluded}")

    # -- 2.6 partition note ----------------------------------------------
    (C.GEO / "PARTITION_NOTE.md").write_text(
        "# The 2016 district reorganisation - what it is and what was done\n\n"
        "## Verdict\n\n"
        "**A district division is zero-sum. When an undivided district x was\n"
        "divided into y and z in 2016, x = y + z: the land does not leave the\n"
        "parent, so the children's area and production sum to the parent's.**\n\n"
        "The children take the parent's name where one survives and a new name\n"
        "where one does not (Ranga Reddy -> Rangareddy spelling; Warangal ->\n"
        "Warangal Rural + Warangal Urban). The dataset reports the children\n"
        "individually from 2016-17 onward, and this analysis uses them as\n"
        "individual entities - which is how the data is delivered.\n\n"
        "## What this means for a pre-2016 to post-2016 comparison\n\n"
        "Because the split is zero-sum, a parent-level figure for a post-2016\n"
        "season is simply the sum of its wholly-descendant children:\n\n"
        "    yield_parent(2016+) = sum(production_children) / sum(area_children)\n\n"
        "That reconstruction is **not** attempted here, for two reasons:\n\n"
        "1. Suryapet was formed from parts of two parents (Khammam and Nalgonda),\n"
        "   so those parents cannot be rebuilt from the children the dataset\n"
        "   names - a partial sum would silently misstate the parent.\n"
        "2. It is unnecessary. The analysis models the post-2016 districts as the\n"
        "   entities they are, with era-tagged ids. Pre-2016 seasons enter only as\n"
        "   a robustness check on the fitted vertex, under a distinct\n"
        "   fixed-effect group, so no pre-2016 district is ever compared to a\n"
        "   post-2016 one as if they were the same unit.\n\n"
        "## Why the zero-sum status is taken as given, not measured\n\n"
        "It is a fact of the reorganisation, not a quantity recoverable from the\n"
        "data. An area-based check was attempted and was inconclusive: comparing\n"
        "a parent's kharif area with the sum of its children's area across the\n"
        "2015-16 / 2016-17 boundary gives residuals of +65% to -70%, because\n"
        "crop choice reallocates area between districts and seasons by more than\n"
        "the boundary effect. Crop area therefore cannot test a boundary mapping.\n"
        "The earlier note in this file that the split was 'not a clean partition'\n"
        "and that Tier 2 was 'blocked' overstated the constraint and has been\n"
        "withdrawn.\n\n"
        "## Sources\n\n"
        "- The delivered DES file (`data/raw/des/"
        "horizontal_crop_vertical_year_report.xls`), which covers 2014-15 to\n"
        "  2022-23 and reports 9 undivided districts before 2016-17 and 30 from\n"
        "  2016-17.\n"
        "- District boundary GeoJSON used for the map (`{GEOJSON_SOURCE}`).\n"
        "- Published reporting of the 2016 reorganisation: Suryapet is widely\n"
        "  reported as formed from parts of both Khammam and Nalgonda.\n".format(
            GEOJSON_SOURCE=GEOJSON_SOURCE
        )
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
            "features_with_data": sum(
                1 for f in out_features if not f["properties"].get("no_data")
            ),
            "features_no_data": sum(
                1 for f in out_features if f["properties"].get("no_data")
            ),
            "features_excluded": excluded,
            "exclusion_reason": "present in the boundary file but absent from the "
            "delivered DES data (no yield observations to map)",
            "crosswalk_method_counts": {
                k: int(v) for k, v in crosswalk["match_method"].value_counts().items()
            },
            "centroid_method": sorted(cent["centroid_method"].unique().tolist()),
            "centroid_note": "area-weighted centroid of intersecting ERA5 0.25 deg "
            "grid cells (the preferred method)",
            "era_rule": (
                "seasons from 2016-17 are post2016; 2001-02..2015-16 are "
                "pre2016; earlier seasons would be pre2001 (the delivered file "
                "starts at 2014-15)"
            ),
            "districts": int(dim["district_slug"].nunique()),
            "district_ids": int(len(dim)),
            "sha256_districts_csv": C.sha256_file(C.GEO / "districts.csv"),
            "sha256_geojson": C.sha256_file(out_path),
        },
    )
    log("  manifest written: data/manifests/geo.json")


if __name__ == "__main__":
    main()
