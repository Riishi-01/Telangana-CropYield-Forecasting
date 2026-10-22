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

    # The forecast charts need the full 9-season record, not just the primary
    # panel: 2014-15 and 2015-16 are 9 undivided parent districts and 2016-17
    # onward are the 32 post-reorganisation districts.  The two blocks are kept
    # separate in the payload and marked with an era flag per row, so the
    # dashboard can draw the boundary break rather than hide it.
    all_seasons = sorted(panel["season"].unique().tolist())
    pre_seasons = [s for s in all_seasons if s < cfg.PRIMARY_PANEL_START]

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
                            round_or_none(r["area_ha"], 1),
                            round_or_none(r["production"], 1),
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

    # -- extended panel: the two pre-2016 seasons -----------------------------
    # 9 undivided parent districts, era-tagged.  Shipped so the forecast
    # charts can show 2014-15 -> 2022-23 with the 2016 boundary marked
    # rather than silently truncating the record.
    extended: dict = {}
    for crop in crops:
        d = panel[(panel["crop"] == crop) & (panel["season"].isin(pre_seasons))]
        if d.empty:
            continue
        per: dict = {}
        for season in pre_seasons:
            sub = d[d["season"] == season]
            if sub.empty:
                continue
            per[season] = [
                {
                    "s": r["district_slug"],
                    "l": str(r["district_label"]),
                    "y": round_or_none(r["yield"], 3),
                    "a": round_or_none(r["area_ha"], 1),
                    "r": round_or_none(r["rain_mm"], 1),
                    "d": int(r["dry_run_max"]),
                    "h": int(r["heat_days"]),
                }
                for _, r in sub.iterrows()
            ]
        extended[crop] = per

    # -- the 2026 forecast ----------------------------------------------------
    forecast: dict = {}
    forecast_meta: dict = {}
    forecast_path = cfg.PROCESSED / "forecast_series.json"
    # the model-selection record, so the page can explain the model that
    # produced each prediction instead of only quoting its output
    fm_path = cfg.PROCESSED / "forecast_models.json"
    fm = cfg.read_json(fm_path) if fm_path.exists() else {}
    if forecast_path.exists():
        fs = cfg.read_json(forecast_path)
        forecast_meta = {
            "area_baseline_season": fs["area_baseline_season"],
            "area_baseline_note": fs["area_baseline_note"],
            "measure": fs["measure"],
            "aggregation": fs["aggregation"],
            "selection_method": fm.get("selection_method", ""),
            "validity_gate": fm.get("validity_gate", ""),
            "baseline": fm.get("crops", {}).get("Rice", {}).get("baseline", ""),
        }
        for crop, res in fs["crops"].items():
            fc = (fm.get("crops") or {}).get(crop, {})
            forecast[crop] = {
                "unit": res["unit"],
                "selected_spec": res["selected_spec"],
                "spec_yield_form": res["spec_yield_form"],
                "skill_rmse": res["skill_rmse"],
                "beats_baseline": res["beats_baseline"],
                "r2": res["r2"],
                "b_rain_per_mm": res["b_rain_per_mm"],
                "rejected_specs": res["rejected_specs"],
                "per_district": res["per_district"],
                "state": res["state"],
                "n_districts": res["n_districts"],
                "n_negative_predicted": res["n_negative_predicted"],
                # the fit behind the prediction
                "train_seasons": fc.get("train_seasons", []),
                "test_seasons": fc.get("test_seasons", []),
                "n_train_rows": fc.get("n_train_rows"),
                "n_test_rows": fc.get("n_test_rows"),
                "cv_ranking": fc.get("cv_ranking", []),
            }

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
                "no_year_fe": s1.get("no_year_fe", {}),
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

        # -- the 2026 implied-yield range, per crop (P4-15) ------------------
        # The 2026 rainfall is OBSERVED (ERA5). What is implied by the fitted
        # curve is NOT a point value - it is a range, because the curve is
        # read at each district's own 2026 rainfall and each district has a
        # different reading.  The range is expressed as % of that district's
        # own median yield, so it is a like-for-like comparison, and the point
        # estimate (the state-mean rainfall read on the curve) sits inside it.
        # This is a READING of the fitted relationship, not a forecast.
        #
        # GATE (P1-7 / P3-13): the range is published ONLY for a crop whose
        # Stage-1 curvature is statistically supported (b2 < 0 and p < 0.05 -
        # the same rule that gates the vertex).  Reading a yield off a curve
        # with no supported relationship is not a reading, it is an
        # extrapolation: for arhar, whose quadratic term is not significant,
        # the 2026 reading returns NEGATIVE yields for 6 of 32 districts,
        # which is physically impossible and must not be published.  Those
        # crops show the observed 2026 rainfall position and say plainly that
        # no implied yield is offered.
        marker["implied_by_crop"] = {}
        marker["implied_withheld"] = {}
        for crop, s1 in (summary.get("crops") or {}).items():
            st1 = s1.get("primary") or {}
            imp = cfg.implied_2026_range(primary, m, crop, st1)
            if imp is None:
                marker["implied_withheld"][crop] = {
                    "p2": st1.get("p2"),
                    "reason": (
                        "the Stage-1 quadratic term is not statistically "
                        f"significant for this crop (p = {st1.get('p2', float('nan')):.3f}), "
                        "so the fitted curve has no supported shape to read a "
                        "yield from. The 2026 rainfall position is shown; no "
                        "implied yield is offered."
                    ),
                }
                continue
            imp["note"] = (
                "A reading of the fitted curve at each district's observed "
                "2026 rainfall, expressed as % of the curve read at that "
                "district's own median rainfall. Not a forecast."
            )
            marker["implied_by_crop"][crop] = imp

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
                "No irrigation, soil, or input data. This is the dominant confound, and "
                "the primary limitation of the whole analysis. Reported effects are "
                "rainfall's marginal association conditional on all other factors being "
                "average, not a causal yield model."
            ),
            "aggregates": "District aggregates, not farm-level.",
            "boundary": (
                "District boundaries were revised in 2016 and 2018. Pre- and post-revision periods "
                "are modelled as distinct fixed-effect groups, not a continuous panel. The choropleth "
                "shows the 32 post-2016 districts; the two pre-2016 seasons are 9 undivided parent "
                "districts and are NOT spatially comparable to this layer."
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
                "Small sample per crop. ~220 district-year observations per crop in the "
                "primary panel."
            ),
            "not_forecast": cfg.DISCLOSURE_2026,
            "forecast_method": (
                "2026 is a model prediction, not a validated forecast. Each crop is forecast "
                "by its own specification, selected by leave-one-season-out cross-validation "
                "inside the fitting period, and each chart carries that model's "
                "out-of-sample skill score against a district-median baseline. Two of the "
                "four models do not beat that baseline, so their predictions should be read "
                "as 'no evidence of a change', not as a forecast."
            ),
            "forecast_area": (
                "2026 planted area does not exist and cannot be forecast. The state-level 2026 "
                "figures are area-weighted using each district's 2022-23 kharif area as the "
                "baseline, applied identically to the 2026 prediction and to the state average, "
                "so the comparison isolates yield from land utilisation. Yield per hectare is "
                "the measure; production totals are the same forecast rescaled by area."
            ),
            "forecast_specimens": (
                "No prediction interval is claimed. With three held-out seasons there is not "
                "enough data to calibrate one honestly, and a false interval would be worse "
                "than none."
            ),
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

    # -- window sensitivity: NOT shipped ---------------------------------------
    # The window-sensitivity panel was retired from the page (ERRATA C14).  The
    # analysis itself is unchanged and stays in the README (section 5) and in
    # figures/f5_window_sensitivity.png; only the dashboard payload is dropped,
    # so the bundle carries nothing the page cannot use.

    # -- the 2026 map layer: its own fixed domains ---------------------------
    # The observed map uses one fixed domain per crop, so the scale never
    # moves between seasons or districts.  The 2026 predictions occupy only
    # the middle of the observed range, so on the observed domain they would
    # all land in the same pale band and the map would say nothing.  The
    # prediction layer therefore has its own fixed domain, per crop, still
    # fixed across the districts and never rescaled by the selection.
    domains_2026: dict = {}
    if forecast:
        for crop, res in forecast.items():
            own = (
                primary[primary["crop"] == crop]
                .groupby("district_slug")["yield"]
                .mean()
            )
            preds = [
                (r["slug"], r["predicted_2026"]) for r in res["per_district"]
            ]
            ys = [p for _, p in preds if p is not None]
            an = [
                100.0 * (p / own[s] - 1.0)
                for s, p in preds
                if p is not None and s in own.index and own[s]
            ]
            if ys:
                domains_2026[crop] = {
                    "yield": [round_or_none(min(ys), 3), round_or_none(max(ys), 3)],
                    "anomaly": (
                        [round_or_none(-max(abs(min(an)), abs(max(an))), 1),
                         round_or_none(max(abs(min(an)), abs(max(an))), 1)]
                        if an else None
                    ),
                }
        # the 2026 rainfall deficit, against each district's own median
        rm = {d["s"]: d["rmed"] for d in districts}
        de = [
            100.0 * (1.0 - v / rm[k])
            for k, v in (marker.get("per_district") or {}).items()
            if rm.get(k) and v
        ]
        if de:
            lim = round_or_none(max(abs(min(de)), abs(max(de))), 1)
            domains_2026["deficit"] = [-lim, lim]

    # -- the state mean kharif rainfall, by season ----------------------------
    # The 2026 state mean (488 mm) needs a state-wise base to be read
    # against, and the report and the dashboard must quote the SAME base.
    # The base is the mean of the nine seasonal state means, 2014-15 to
    # 2022-23: each season counts once, so a season with fewer reporting
    # districts does not weigh less.
    rain_by_season = (
        panel.groupby("season")["rain_mm"].mean().round(1).to_dict()
    )
    rain_state = {
        "per_season": rain_by_season,
        "avg_9season": round(float(sum(rain_by_season.values()) / len(rain_by_season)), 1),
        "primary_avg": round(
            float(
                panel[panel["season"] >= cfg.PRIMARY_PANEL_START]
                .groupby("season")["rain_mm"]
                .mean()
                .mean()
            ),
            1,
        ),
        "definition": (
            "the mean of the seasonal state means over 2014-15 to 2022-23; "
            "each season counts once"
        ),
    }

    bundle = {
        "meta": meta,
        "crops": crops,
        "crop_labels": cfg.CROP_LABELS,
        "crop_colors": cfg.CROP_COLORS,
        "modelled_crops": [c for c in cfg.MODELLED_CROPS if c in crops],
        "seasons": seasons,
        "all_seasons": all_seasons,
        "pre_seasons": pre_seasons,
        "primary_panel_start": cfg.PRIMARY_PANEL_START,
        "districts": districts,
        "panel": panel_data,
        "series": series,
        "extended": extended,
        "forecast": forecast,
        "forecast_meta": forecast_meta,
        "models": models,
        "domains": {**domains, "deficit": [-deficit_lim, deficit_lim]},
        "domains_2026": domains_2026,
        "marker": marker,
        "rain_state": rain_state,
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
