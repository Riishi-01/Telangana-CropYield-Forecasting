"""Step 10 - Build the interactive dashboard data bundle.

Writes:
  dashboard/data/bundle.js   window.TA_DATA = {...}   (analysis data)
  dashboard/data/geo.js      window.TA_GEO  = {...}   (district boundaries)

Both are JavaScript, not JSON, on purpose: `fetch()` of a local JSON file is
blocked by the browser's CORS rules when the page is opened from disk, so
inlining the payloads keeps the dashboard working from `file://` as well as
from a static host, with no server anywhere.

Authority: plan/SRS.md §7.4 ; plan/GUIDE.md Step 11.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

VERSION = cfg.data_version()
GEO_NDIGITS = 3  # ~110 m, plenty for a state map


def round_or_none(value, digits=3):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return round(float(value), digits)


def simplify_ring(ring, ndigits=GEO_NDIGITS):
    out = []
    for pt in ring:
        p = [round(float(pt[0]), ndigits), round(float(pt[1]), ndigits)]
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def main() -> None:
    cfg.check_determinism()
    log("Step 10: dashboard bundle")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    summary = cfg.read_json(cfg.PROCESSED / "model_summary.json")
    manifest = cfg.read_json(cfg.MANIFESTS / "fetch_manifest.json")
    geo_manifest = cfg.read_json(cfg.MANIFESTS / "geo.json")
    features_manifest = cfg.read_json(cfg.MANIFESTS / "features.json")
    primary = panel[panel["is_primary_panel"]].copy()

    # -- districts ------------------------------------------------------------
    districts_csv = pd.read_csv(cfg.GEO / "districts.csv")
    districts_csv = districts_csv.sort_values("district_slug").drop_duplicates("district_slug")
    slugs = districts_csv["district_slug"].tolist()
    districts = [
        {
            "s": r.district_slug,
            "l": r.des_name,
            "g": r.geojson_name,
            "lat": round_or_none(r.lat, 4),
            "lon": round_or_none(r.lon, 4),
            "nd": False,
        }
        for r in districts_csv.itertuples()
    ]
    slug_index = {d["s"]: i for i, d in enumerate(districts)}

    seasons = sorted(primary["season"].unique().tolist())
    # crop scope is the four target crops, in the canonical order
    crops = [c for c in cfg.TARGET_CROPS if c in primary["crop"].unique()]

    # per-district median kharif rainfall over the primary panel, used as the
    # reference for the rainfall-deficit map metric (each district vs its own norm)
    rain_ref = (
        primary.drop_duplicates(subset=["district_slug", "season"])
        .groupby("district_slug")["rain_mm"].median()
    )
    districts = [
        {
            **d,
            "rmed": round_or_none(rain_ref.get(d["s"]), 1),
        }
        for d in districts
    ]

    # fixed domain for the deficit metric, computed across the whole panel so
    # the scale never rescales between crops, seasons or districts
    dd = primary.drop_duplicates(subset=["district_slug", "season"])
    dd = dd[dd["district_slug"].isin(rain_ref.index)].copy()
    dd["deficit"] = 100.0 * (
        dd["rain_mm"] / dd["district_slug"].map(rain_ref) - 1.0
    )
    deficit_lim = round_or_none(max(abs(dd["deficit"].min()), abs(dd["deficit"].max())), 1)

    # -- panel matrix ---------------------------------------------------------
    # panel[crop][season] -> array aligned with `districts`
    # each entry: [yield, anomaly_pct, rain_mm, dry_run_max, dry_days_ge5,
    #              heat_days, vpd_mean, rain_days]
    panel_data: dict = {}
    domains: dict = {}
    series: dict = {}

    for crop in crops:
        d = primary[primary["crop"] == crop]
        if d.empty:
            continue
        per_season: dict = {}
        crop_series: dict = {}
        anomalies = d["yield_anom_pct"].dropna()
        yields = d["yield"].dropna()
        domains[crop] = {
            "anomaly": [
                round_or_none(-max(abs(anomalies.min()), abs(anomalies.max())), 1),
                round_or_none(max(abs(anomalies.min()), abs(anomalies.max())), 1),
            ],
            "yield": [round_or_none(yields.min(), 3), round_or_none(yields.max(), 3)],
        }
        for season in seasons:
            sub = d[d["season"] == season]
            by_slug = sub.set_index("district_slug")
            arr = []
            for slug in slugs:
                if slug in by_slug.index:
                    r = by_slug.loc[slug]
                    arr.append(
                        [
                            round_or_none(r["yield"], 3),
                            round_or_none(r["yield_anom_pct"], 1),
                            round_or_none(r["rain_mm"], 1),
                            int(r["dry_run_max"]),
                            int(r["dry_days_ge5"]),
                            int(r["heat_days"]),
                            round_or_none(r["vpd_mean"], 2),
                            int(r["rain_days"]),
                        ]
                    )
                else:
                    arr.append(None)
            per_season[season] = arr
            if not sub.empty:
                crop_series[season] = [
                    round_or_none(sub["rain_mm"].quantile(0.10), 1),
                    round_or_none(sub["rain_mm"].median(), 1),
                    round_or_none(sub["rain_mm"].quantile(0.90), 1),
                    round_or_none(sub["yield"].quantile(0.10), 3),
                    round_or_none(sub["yield"].median(), 3),
                    round_or_none(sub["yield"].quantile(0.90), 3),
                    len(sub),
                ]
        panel_data[crop] = per_season
        series[crop] = crop_series

    # -- models ---------------------------------------------------------------
    models: dict = {}
    for crop in cfg.MODELLED_CROPS:
        if crop not in panel_data:
            continue
        s1 = summary["crops"].get(crop, {})
        s2 = summary.get("stage2", {}).get(crop, {})
        va = summary.get("validation", {}).get("crops", {}).get(crop, {})
        models[crop] = {
            "stage1": s1.get("primary", {}),
            "stage1_robust": {
                "no_season_fe": s1.get("no_season_fe", {}),
                "linear_only": s1.get("linear_only", {}),
                "extended_panel": s1.get("extended_panel", {}),
            },
            "stage2": s2,
            "validation": va,
            "unit": s1.get("primary", {}).get("unit", ""),
            "modelled": True,
        }
    for crop in panel_data:
        models.setdefault(crop, {"modelled": False, "unit": "", "stage1": {}})

    # -- 2026 marker ----------------------------------------------------------
    marker = {"available": False}
    marker_path = cfg.INTERIM / "features_2026.parquet"
    if marker_path.exists():
        m = pd.read_parquet(marker_path)
        # Rainfall is a district-season variable, so the historical distribution
        # it is compared against must count each district-season once - the
        # panel repeats it once per crop.
        hist = (
            primary.drop_duplicates(subset=["district_slug", "season"])["rain_mm"]
        )
        marker = {
            "available": True,
            "per_district": {
                r.district_slug: round_or_none(r.rain_mm, 1)
                for r in m.itertuples()
            },
            "state_mean": round_or_none(m["rain_mm"].mean(), 1),
            "p10": round_or_none(m["rain_mm"].quantile(0.10), 1),
            "p90": round_or_none(m["rain_mm"].quantile(0.90), 1),
            "min": round_or_none(m["rain_mm"].min(), 1),
            "max": round_or_none(m["rain_mm"].max(), 1),
            "historical_min": round_or_none(hist.min(), 1),
            "historical_mean": round_or_none(hist.mean(), 1),
            "historical_max": round_or_none(hist.max(), 1),
            "percentile_in_history": round_or_none(
                (hist < m["rain_mm"].mean()).mean() * 100, 1
            ),
            "districts_below_historical_min": int(
                (m["rain_mm"] < hist.min()).sum()
            ),
            "n_districts": int(len(m)),
        }

    # -- metadata / disclosures ----------------------------------------------
    meta = {
        "data_version": VERSION,
        "built_utc": cfg.utc_now_iso(),
        "panel_created_utc": manifest["created_utc"],
        "season_window": "1 Jun – 30 Sep (official kharif sowing window)",
        "ingest_window": f"{manifest['temp_window'][0]} – {manifest['temp_window'][1]}",
        "weather_source": "ERA5 reanalysis via the Open-Meteo archive API",
        "weather_licence": manifest["weather_licence"],
        "yield_source": manifest["yield_source"],
        "geojson_source": manifest["geojson_source_url"],
        "centroid_method": ", ".join(manifest["centroid_method"]),
        "rain_day_threshold_mm": features_manifest["rain_day_threshold_mm"],
        "model_spec": summary["spec_primary"].replace("y ~", "yield ~", 1),
        "split": (
            f"train ≤ {summary['validation']['train_last_season']} · "
            f"test ≥ {summary['validation']['test_first_season']} (chronological, never random)"
        ),
        "baseline": summary["validation"]["baseline"],
        "vertex_rule": summary["vertex_rule"],
        "disclosures": {
            "reanalysis": (
                "Reanalysis, not observation. ERA5 is a model-assimilated reanalysis product at "
                "0.25° (~25 km) resolution. It is not IMD station gauge data."
            ),
            "convective": (
                "ERA5 is known to underestimate convective rainfall over dryland interiors. "
                "Absolute rainfall totals may be biased low."
            ),
            "confound": (
                "No irrigation, soil or input data. Reported effects are rainfall's marginal "
                "association conditional on all other factors being average, not a causal yield model."
            ),
            "aggregates": "District aggregates, not farm-level.",
            "boundary": (
                "District boundaries were revised in 2016 and 2018. Pre- and post-revision periods "
                "are modelled as distinct fixed-effect groups, not a continuous panel."
            ),
            "sowing": (
                "Sowing window ≠ season. Jun–Sep is the official kharif sowing window; cotton and "
                "arhar grow to Nov–Dec, so late-season rainfall is undercounted."
            ),
            "agency": (
                "DES agency discontinuity. Pre-2014 figures originate with undivided Andhra Pradesh "
                "DES; post-2014 with Telangana DES. Estimation methodology may differ."
            ),
            "cotton": "Cotton is reported in bales, not tonnes, and is modelled on that scale.",
            "sample": (
                "Small sample per crop: ~220 district-year observations per crop in the primary panel."
            ),
            "not_forecast": cfg.DISCLOSURE_2026,
            "attribution": (
                "Attribution. ERA5 via Open-Meteo — CC BY 4.0. DES — Govt. of India open data. "
                "District boundaries: Open Government Data / community GeoJSON (see sources)."
            ),
            "percentiles": (
                "Rule-based percentile bands are descriptive, not inferential. No confidence "
                "intervals are claimed."
            ),
        },
    }

    # -- window sensitivity (optional; present once step 12 has run) ----------
    window_sensitivity = {"available": False}
    ws_path = cfg.PROCESSED / "window_sensitivity.json"
    if ws_path.exists():
        ws = cfg.read_json(ws_path)
        window_sensitivity = {
            "available": True,
            "windows": {k: v["label"] for k, v in ws["windows"].items()},
            "window_order": ["jul_sep", "jun_sep", "jun_oct"],
            "crops": {
                crop: {
                    w: {
                        "p2": r["p2"],
                        "r2": r["r2"],
                        "vertex_reported": r["vertex_reported"],
                        "vertex_mm": r["vertex_mm"],
                        "n": r["n"],
                    }
                    for w, r in ws["crops"][crop].items()
                }
                for crop in crops
                if crop in ws["crops"]
            },
        }

    bundle = {
        "meta": meta,
        "crops": crops,
        "crop_labels": cfg.CROP_LABELS,
        "modelled_crops": [c for c in cfg.MODELLED_CROPS if c in crops],
        "seasons": seasons,
        "districts": districts,
        "panel": panel_data,
        "series": series,
        "models": models,
        "domains": {**domains, "deficit": [-deficit_lim, deficit_lim]},
        "marker": marker,
        "window_sensitivity": window_sensitivity,
    }

    (cfg.DASHBOARD_DATA / "bundle.js").write_text(
        "/* Generated by src/10_build_dashboard.py - do not edit by hand. */\n"
        "window.TA_DATA = " + json.dumps(bundle, separators=(",", ":")) + ";\n"
    )
    size = (cfg.DASHBOARD_DATA / "bundle.js").stat().st_size
    log(f"  wrote dashboard/data/bundle.js ({size/1e6:.2f} MB)")

    # -- geometry -------------------------------------------------------------
    geo = json.loads((cfg.GEO / "districts.geojson").read_text())
    out_features = []
    for feat in geo["features"]:
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            geom = {
                "type": "Polygon",
                "coordinates": [simplify_ring(r) for r in geom["coordinates"]],
            }
        else:
            geom = {
                "type": "MultiPolygon",
                "coordinates": [[simplify_ring(r) for r in poly] for poly in geom["coordinates"]],
            }
        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "slug": feat["properties"].get("slug", ""),
                    "name": feat["properties"]["D_NAME"],
                    "no_data": bool(feat["properties"].get("no_data", False)),
                },
                "geometry": geom,
            }
        )
    (cfg.DASHBOARD_DATA / "geo.js").write_text(
        "/* Generated by src/10_build_dashboard.py - do not edit by hand. */\n"
        "window.TA_GEO = " + json.dumps({"type": "FeatureCollection", "features": out_features},
                                       separators=(",", ":")) + ";\n"
    )
    log(f"  wrote dashboard/data/geo.js "
        f"({(cfg.DASHBOARD_DATA / 'geo.js').stat().st_size/1e6:.2f} MB)")

    # -- manifest -------------------------------------------------------------
    cfg.write_json(
        cfg.MANIFESTS / "dashboard.json",
        {
            "artifact": "dashboard",
            "created_utc": cfg.utc_now_iso(),
            "data_version": VERSION,
            "bundle_js": "dashboard/data/bundle.js",
            "bundle_sha256": cfg.sha256_file(cfg.DASHBOARD_DATA / "bundle.js"),
            "geo_js": "dashboard/data/geo.js",
            "geo_sha256": cfg.sha256_file(cfg.DASHBOARD_DATA / "geo.js"),
            "panel_sha256": manifest["sha256"],
            "crops": len(crops),
            "modelled_crops": cfg.MODELLED_CROPS,
            "seasons": seasons,
            "districts": len(districts),
            "marker_2026_available": marker["available"],
            "libraries": {
                "plotly": "2.35.2 (MIT)",
                "leaflet": "1.9.4 (BSD-2-Clause)",
                "fonts": "Instrument Serif, IBM Plex Sans, IBM Plex Mono (SIL OFL 1.1)",
            },
            "offline": "all libraries, fonts and data are served from the repository; no CDN",
        },
    )
    log("  manifest written: data/manifests/dashboard.json")


if __name__ == "__main__":
    main()
