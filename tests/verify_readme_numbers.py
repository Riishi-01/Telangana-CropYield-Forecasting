"""Verify the numbers printed in README.md against the built artefacts.

Acceptance criterion A1: "Every number in README traces to a committed
artefact.  Spot-check 5 values against data/processed/".  This script does
that for every headline number the README states, so the check is repeatable
rather than a one-off read.

Usage:  PYTHONHASHSEED=0 .venv/bin/python tests/verify_readme_numbers.py
Exit code 0 = every number agrees.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import common as cfg  # noqa: E402

README = ROOT / "README.md"


def close(a, b, tol=5e-4):
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def main() -> None:
    models = cfg.read_json(cfg.PROCESSED / "model_summary.json")
    manifest = cfg.read_json(cfg.MANIFESTS / "fetch_manifest.json")
    geo = cfg.read_json(cfg.MANIFESTS / "geo.json")
    weather = cfg.read_json(cfg.MANIFESTS / "weather_fetch.json")
    des = cfg.read_json(cfg.MANIFESTS / "des_ingest.json")
    clean_meta = cfg.read_json(cfg.PROCESSED / "crops_kharif_clean.metadata.json")
    ws = cfg.read_json(cfg.PROCESSED / "window_sensitivity.json")
    readme = README.read_text()

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    def in_readme(text: str) -> bool:
        """The README must actually contain this number, formatted as written."""
        return text in readme

    s1 = models["crops"]
    s2 = models["stage2"]
    val = models["validation"]["crops"]

    # ---- §3 the preprocessed dataset -------------------------------------
    check("clean dataset has 940 rows", clean_meta["rows"] == 940, str(clean_meta["rows"]))
    check("clean dataset has 13 columns", len(clean_meta["columns"]) == 13,
          str(len(clean_meta["columns"])))
    check("clean dataset covers 4 crops", len(clean_meta["scope"]["crops"]) == 4,
          str(clean_meta["scope"]["crops"]))
    check("clean dataset spans 2014-15 to 2022-23",
          clean_meta["scope"]["season_range"] == ["2014-15", "2022-23"],
          str(clean_meta["scope"]["season_range"]))
    check("12 rows removed by the quality rules",
          clean_meta["removed"]["quality_rule_rows"] == 12,
          str(clean_meta["removed"]["quality_rule_rows"]))
    check("32 out-of-scope crop groups dropped",
          len(clean_meta["removed"]["out_of_scope_crop_groups"]) == 32,
          str(len(clean_meta["removed"]["out_of_scope_crop_groups"])))
    check("identity gate passed on every row",
          clean_meta["identity_gate"] == "passed", clean_meta["identity_gate"])
    check("cotton is in bales, the rest in tonnes",
          clean_meta["units"]["Cotton(lint)"]["yield_unit"] == "bales/ha"
          and clean_meta["units"]["Rice"]["yield_unit"] == "t/ha",
          json.dumps(clean_meta["units"]))
    check("source parsed shape is (238, 111)",
          des["parsed_shape"] == [238, 111], str(des["parsed_shape"]))
    check("README states 940 rows x 13 columns", in_readme("940 rows × 13 columns"))

    # ---- §5 Stage 1 -------------------------------------------------------
    for crop, n, b1, p1, b2, p2, r2 in [
        ("Cotton(lint)", 220, 0.001466, 0.118, -4.35e-07, 0.293, 0.570),
        ("Arhar/Tur", 219, 0.004614, 0.090, -2.23e-06, 0.069, 0.249),
        ("Moong(Green Gram)", 209, -0.000005, 0.986, -4.53e-08, 0.714, 0.545),
        ("Rice", 220, 0.001474, 0.005, -5.44e-07, 0.018, 0.732),
    ]:
        p = s1[crop]["primary"]
        check(f"{crop}: n = {n}", p["n_rows"] == n, str(p["n_rows"]))
        check(f"{crop}: b1 = {b1}", close(p["b1"], b1), str(p["b1"]))
        check(f"{crop}: p(b1) = {p1}", close(p["p1"], p1, 1e-2), str(p["p1"]))
        check(f"{crop}: b2 = {b2}", close(p["b2"], b2, 1e-2), str(p["b2"]))
        check(f"{crop}: p(b2) = {p2}", close(p["p2"], p2, 1e-2), str(p["p2"]))
        check(f"{crop}: R2 = {r2}", close(p["r2"], r2, 1e-3), str(p["r2"]))

    for crop in ("Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)"):
        check(f"{crop}: no vertex reported",
              s1[crop]["primary"]["vertex_reported"] is False,
              str(s1[crop]["primary"]["vertex_reason"]))
    rice = s1["Rice"]["primary"]
    check("rice: R* = 1354 mm", close(rice["vertex_mm"], 1354.42, 1e-3),
          str(rice["vertex_mm"]))
    check("rice: 95% CI 1021-1688",
          close(rice["vertex_ci95_mm"][0], 1021.22, 1e-3)
          and close(rice["vertex_ci95_mm"][1], 1687.61, 1e-3),
          str(rice["vertex_ci95_mm"]))
    check("rice: vertex at the 95th percentile",
          close(rice["vertex_frac_obs_below"], 0.95, 1e-2), str(rice["vertex_frac_obs_below"]))
    check("rice: no vertex without season fixed effects",
          s1["Rice"]["no_year_fe"]["vertex_reported"] is False)
    check("rice: extended panel vertex 1350 mm",
          close(s1["Rice"]["extended_panel"]["vertex_mm"], 1349.63, 1e-3),
          str(s1["Rice"]["extended_panel"]["vertex_mm"]))
    check("README quotes the rice vertex as 1,354 mm", in_readme("1,354 mm"))
    check("README quotes the rice CI", in_readme("1,021 – 1,688"))

    # ---- §5 window sensitivity -------------------------------------------
    for crop, cells in [
        ("Cotton(lint)", [("jul_sep", 0.142, None), ("jun_sep", 0.293, None),
                          ("jun_oct", 0.315, None)]),
        ("Arhar/Tur", [("jul_sep", 0.223, None), ("jun_sep", 0.069, None),
                       ("jun_oct", 0.406, None)]),
        ("Moong(Green Gram)", [("jul_sep", 0.646, None), ("jun_sep", 0.714, None),
                              ("jun_oct", 0.386, None)]),
        ("Rice", [("jul_sep", 0.001, 1177), ("jun_sep", 0.018, 1354),
                  ("jun_oct", 0.006, 1411)]),
    ]:
        for w, p, v in cells:
            r = ws["crops"][crop][w]
            check(f"{crop}/{w}: p(b2) = {p}", close(r["p2"], p, 1e-2), str(r["p2"]))
            if v is None:
                check(f"{crop}/{w}: no vertex", r["vertex_reported"] is False)
            else:
                check(f"{crop}/{w}: R* = {v}", close(r["vertex_mm"], v, 1e-2),
                      str(r["vertex_mm"]))
    check("window conclusion is stable for every crop",
          all(
              len({ws["crops"][c][w]["vertex_reported"] for w in
                   ("jul_sep", "jun_sep", "jun_oct")}) == 1
              for c in ws["crops"]
          ))

    # ---- §5 Stage 2 -------------------------------------------------------
    for crop, r2_1, r2_2, d_r2, d_adj, f_p in [
        ("Cotton(lint)", 0.570, 0.600, 0.030, 0.023, 0.024),
        ("Arhar/Tur", 0.249, 0.269, 0.020, -0.001, 0.448),
        ("Moong(Green Gram)", 0.545, 0.558, 0.013, -0.001, 0.460),
        ("Rice", 0.732, 0.739, 0.007, -0.001, 0.487),
    ]:
        s = s2[crop]
        check(f"{crop}: R2 {r2_1} -> {r2_2}",
              close(s["r2_stage1"], r2_1, 1e-2) and close(s["r2_stage2"], r2_2, 1e-2),
              f"{s['r2_stage1']} -> {s['r2_stage2']}")
        check(f"{crop}: dR2 = {d_r2}", close(s["delta_r2"], d_r2, 1e-2), str(s["delta_r2"]))
        check(f"{crop}: dAdjR2 = {d_adj}", close(s["delta_adj_r2"], d_adj, 1e-2),
              str(s["delta_adj_r2"]))
        check(f"{crop}: partial F p = {f_p}", close(s["partial_f_p"], f_p, 1e-2),
              str(s["partial_f_p"]))
    check("stage 2 arhar has a significant quadratic (p = 0.026)",
          close(s2["Arhar/Tur"]["p2"], 0.026, 1e-2), str(s2["Arhar/Tur"]["p2"]))
    check("stage 2 arhar vertex 1083 mm",
          close(s2["Arhar/Tur"]["vertex_mm"], 1083.13, 1e-2),
          str(s2["Arhar/Tur"]["vertex_mm"]))

    # ---- §5 validation ----------------------------------------------------
    for crop, rmse_m, rmse_b, skill, skill_nf in [
        ("Cotton(lint)", 0.788, 0.561, -0.405, -0.354),
        ("Arhar/Tur", 1.885, 1.949, 0.033, 0.031),
        ("Moong(Green Gram)", 0.261, 0.255, -0.023, -0.035),
        ("Rice", 0.502, 0.452, -0.111, -0.010),
    ]:
        v = val[crop]
        check(f"{crop}: RMSE model {rmse_m}", close(v["rmse_model"], rmse_m, 1e-2),
              str(v["rmse_model"]))
        check(f"{crop}: RMSE baseline {rmse_b}", close(v["rmse_baseline"], rmse_b, 1e-2),
              str(v["rmse_baseline"]))
        check(f"{crop}: skill {skill}", close(v["skill_rmse"], skill, 1e-2),
              str(v["skill_rmse"]))
        check(f"{crop}: no-FE skill {skill_nf}",
              close(v["no_year_fe"]["skill_rmse"], skill_nf, 1e-2),
              str(v["no_year_fe"]["skill_rmse"]))
    check("split is train <= 2019-20 / test >= 2020-21",
          models["validation"]["train_last_season"] == "2019-20"
          and models["validation"]["test_first_season"] == "2020-21")

    # ---- §5 the 2026 reading ---------------------------------------------
    marker_path = cfg.INTERIM / "features_2026.parquet"
    if marker_path.exists():
        import pandas as pd

        m = pd.read_parquet(marker_path)
        check("2026 state-mean rainfall = 488 mm",
              close(m["rain_mm"].mean(), 487.9, 1e-2), str(round(m["rain_mm"].mean(), 1)))
        check("2026 median = 439 mm", close(m["rain_mm"].median(), 439.4, 1e-2),
              str(round(m["rain_mm"].median(), 1)))
        check("2026 p10-p90 = 285-731 mm",
              close(m["rain_mm"].quantile(0.10), 285.2, 1e-2)
              and close(m["rain_mm"].quantile(0.90), 731.2, 1e-2),
              f"{m['rain_mm'].quantile(0.10):.1f}-{m['rain_mm'].quantile(0.90):.1f}")
        check("2026 range 248-816 mm",
              close(m["rain_mm"].min(), 248.2, 1e-2)
              and close(m["rain_mm"].max(), 816.1, 1e-2),
              f"{m['rain_mm'].min():.1f}-{m['rain_mm'].max():.1f}")
        panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{cfg.data_version()}.parquet")
        prim = panel[panel["is_primary_panel"]]
        # rainfall is a district-season variable: count each district-season once,
        # not once per crop
        hist_distinct = prim.drop_duplicates(subset=["district_slug", "season"])["rain_mm"]
        check("fitted-period rainfall range 374-1827 mm",
              close(prim["rain_mm"].min(), 373.7, 1e-2)
              and close(prim["rain_mm"].max(), 1826.7, 1e-2),
              f"{prim['rain_mm'].min():.1f}-{prim['rain_mm'].max():.1f}")
        check("2026 is the 1.4th percentile of the fitted period",
              close((hist_distinct < m["rain_mm"].mean()).mean() * 100, 1.36, 1e-2),
              f"{(hist_distinct < m['rain_mm'].mean()).mean()*100:.2f}")
        check("9 of 32 districts fall below the observed minimum",
              int((m["rain_mm"] < prim["rain_mm"].min()).sum()) == 9,
              str(int((m["rain_mm"] < prim["rain_mm"].min()).sum())))
    else:
        check("2026 marker features present", False, "features_2026.parquet missing")

    # ---- §2/§9 provenance --------------------------------------------------
    check("weather has 113984 district-days", weather["rows"] == 113984,
          str(weather["rows"]))
    check("no NaN in the weather record",
          all(v == 0 for v in weather["nan_rate"].values()), str(weather["nan_rate"]))
    check("32 districts on the primary panel", manifest["districts"] == 32,
          str(manifest["districts"]))
    check("panel has 940 rows", manifest["rows"] == 940, str(manifest["rows"]))
    check("primary panel has 868 rows", manifest["rows_primary_panel"] == 868,
          str(manifest["rows_primary_panel"]))
    check("32 districts have an ERA5-grid centroid",
          geo["centroid_method"] == ["era5_grid_area_weighted_centroid"],
          str(geo["centroid_method"]))
    check("boundary join is 32 of 32", geo["features_with_data"] == 32,
          str(geo["features_with_data"]))
    check("Hyderabad carried as an explicit no-data feature",
          geo["features_no_data"] == 1, str(geo["features_no_data"]))
    check("13 names joined by alias",
          geo["crosswalk_method_counts"].get("alias_table") == 13,
          str(geo["crosswalk_method_counts"]))
    check("DATA_VERSION is 1.1.0", cfg.data_version() == "1.1.0", cfg.data_version())
    check("README states the DATA_VERSION", in_readme("`1.1.0`"))

    # ---- P1-6 robustness grid ---------------------------------------------
    grid_path = cfg.PROCESSED / "robustness_grid.json"
    if grid_path.exists():
        grid = cfg.read_json(grid_path)
        gs = grid["summary"]
        # the shipped specification's correlation, per crop
        for crop, r in [("Cotton(lint)", 0.066), ("Arhar/Tur", -0.020),
                        ("Moong(Green Gram)", -0.183), ("Rice", 0.221)]:
            check(f"grid: {crop} shipped r = {r:+.3f}",
                  close(gs[crop]["shipped_r"], r, 5e-3),
                  f"{gs[crop]['shipped_r']:+.4f}")
        # rice survives within-district; cotton's only significance is pooled
        check("grid: rice survives within-district",
              gs["Rice"]["significant_within_district"] is True, str(gs["Rice"]))
        check("grid: cotton's pooled significance is flagged as a confound",
              gs["Cotton(lint)"]["pooled_only_confound"] is True,
              str(gs["Cotton(lint)"]))
        check("grid: arhar and moong have no significant specification",
              gs["Arhar/Tur"]["cells_with_significant_quadratic"] == 0
              and gs["Moong(Green Gram)"]["cells_with_significant_quadratic"] == 0,
              f"{gs['Arhar/Tur']['cells_with_significant_quadratic']},"
              f"{gs['Moong(Green Gram)']['cells_with_significant_quadratic']}")
        # the alignment evidence
        check("grid: the +1 yr shift flips rice's sign",
              (gs["Rice"]["alignment_check"]["r_implemented"] or 0) > 0
              and (gs["Rice"]["alignment_check"]["r_shifted_plus1"] or 0) < 0,
              str(gs["Rice"]["alignment_check"]))
        check("grid: row 7 (ERA5-Land) is deferred, not dropped",
              grid["row_7_status"].startswith("deferred"), grid["row_7_status"])
        # the README table must agree with the artefact
        for r in ["+0.066", "−0.020", "−0.183", "+0.221", "+0.256"]:
            check(f"README grid shows {r}", r in readme, r)
    else:
        check("robustness grid artefact present", False, "robustness_grid.json missing")

    # ---- P1-9 slope heterogeneity -----------------------------------------
    het_path = cfg.PROCESSED / "slope_heterogeneity.json"
    if het_path.exists():
        het = cfg.read_json(het_path)["crops"]
        for crop, p in [("Cotton(lint)", 0.076), ("Arhar/Tur", 0.087),
                        ("Moong(Green Gram)", 0.600), ("Rice", 0.789)]:
            check(f"heterogeneity LRT p for {crop} = {p}",
                  close(het[crop]["lrt_p_value"], p, 5e-3),
                  f"{het[crop]['lrt_p_value']:.4f}")
            check(f"heterogeneity LRT is a valid optimum for {crop}",
                  het[crop]["lrt_valid"] is True, str(het[crop].get("lrt_valid")))
        check("no crop rejects the shared-slope assumption",
              all(not het[c]["significant_at_05"] for c in het),
              str({c: het[c]["significant_at_05"] for c in het}))
    else:
        check("slope heterogeneity artefact present", False,
              "slope_heterogeneity.json missing")

    # ---- P4-15 the 2026 implied range -------------------------------------
    bundle_path = cfg.DASHBOARD_DATA / "bundle.js"
    if bundle_path.exists():
        raw = bundle_path.read_text()
        bundle = json.loads(raw[raw.index("{"):].rstrip().rstrip(";"))
        marker = bundle["marker"]
        published = marker.get("implied_by_crop", {})
        withheld = marker.get("implied_withheld", {})
        check("2026 implied range published for rice only",
              set(published) == {"Rice"}, str(sorted(published)))
        check("2026 implied range withheld for the other three crops",
              set(withheld) == {"Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)"},
              str(sorted(withheld)))
        if "Rice" in published:
            imp = published["Rice"]
            check("rice 2026 implied band p10 = -12.7%",
                  close(imp["pct_p10"], -12.7, 5e-2), f"{imp['pct_p10']}")
            check("rice 2026 implied band p90 = -4.9%",
                  close(imp["pct_p90"], -4.9, 5e-2), f"{imp['pct_p90']}")
            check("rice 2026 state-mean reading is inside the band",
                  imp["pct_p10"] <= imp["state_mean_pct_vs_normal"] <= imp["pct_p90"],
                  f"{imp['pct_p10']} <= {imp['state_mean_pct_vs_normal']} <= {imp['pct_p90']}")
            check("every published implied yield is positive",
                  all(r["implied_yield"] > 0 for r in imp["per_district"]),
                  str(min(r["implied_yield"] for r in imp["per_district"])))
        # the crop identity palette must be in the bundle
        check("crop identity palette shipped in the bundle",
              set(bundle.get("crop_colors", {})) == {
                  "Rice", "Arhar/Tur", "Moong(Green Gram)", "Cotton(lint)"},
              str(sorted(bundle.get("crop_colors", {}))))

        # ---- C10 the 2026 forecast ----------------------------------------
        fc = bundle.get("forecast", {})
        check("the forecast block ships all four crops",
              set(fc) == {"Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)", "Rice"},
              str(sorted(fc)))
        for crop, skill in [("Cotton(lint)", -0.235), ("Arhar/Tur", 0.0055),
                            ("Moong(Green Gram)", -0.017), ("Rice", 0.078)]:
            check(f"forecast skill for {crop} = {skill:+.3f}",
                  close(fc[crop]["skill_rmse"], skill, 5e-4),
                  f"{fc[crop]['skill_rmse']:.4f}")
        # the state figures, area-weighted on 2022-23 area
        for crop, y26, ref, pct in [("Cotton(lint)", 2.029, 2.645, -23.3),
                                    ("Arhar/Tur", 0.837, 0.771, 8.6),
                                    ("Moong(Green Gram)", 0.756, 0.618, 22.4),
                                    ("Rice", 3.151, 3.327, -5.3)]:
            st = fc[crop]["state"]
            check(f"2026 yield/area for {crop} = {y26}",
                  close(st["yield_2026_per_ha"], y26, 5e-3),
                  f"{st['yield_2026_per_ha']}")
            check(f"reference yield/area for {crop} = {ref}",
                  close(st["reference_yield_per_ha"], ref, 5e-3),
                  f"{st['reference_yield_per_ha']}")
            check(f"2026 change for {crop} = {pct:+.1f}%",
                  close(st["pct_vs_reference"], pct, 5e-2),
                  f"{st['pct_vs_reference']}")
            # the total and the yield/area must agree in percentage
            pct_total = 100.0 * (st["total_2026"] / st["reference_total_same_area"] - 1.0)
            check(f"the total and the yield/area agree for {crop}",
                  abs(pct_total - st["pct_vs_reference"]) < 0.05,
                  f"{pct_total:.3f} vs {st['pct_vs_reference']}")
            check(f"no negative predicted yields for {crop}",
                  fc[crop]["n_negative_predicted"] == 0,
                  str(fc[crop]["n_negative_predicted"]))
        # arhar's quadratic must be recorded as rejected
        rejected = [r["spec"] for r in fc["Arhar/Tur"]["rejected_specs"]]
        check("arhar's quadratic is recorded as rejected on validity",
              "S1_quadratic" in rejected, str(rejected))
        check("the rejection reason names the negative yields",
              any("non-positive" in r["reason"]
                  for r in fc["Arhar/Tur"]["rejected_specs"]),
              str([r["reason"][:40] for r in fc["Arhar/Tur"]["rejected_specs"]]))
        # the area baseline must be stated
        fmeta = bundle.get("forecast_meta", {})
        check("the area baseline is stated in the forecast",
              fmeta.get("area_baseline_season") == "2022-23",
              str(fmeta.get("area_baseline_season")))
        check("the area baseline note explains the assumption",
              "does not exist" in fmeta.get("area_baseline_note", ""),
              fmeta.get("area_baseline_note", "")[:60])
    else:
        check("dashboard bundle present", False, "bundle.js missing")

    # ---- C10 the per-crop model selection ---------------------------------
    fm_path = cfg.PROCESSED / "forecast_models.json"
    if fm_path.exists():
        fm = cfg.read_json(fm_path)
        for crop, spec in [("Cotton(lint)", "S1_linear"), ("Arhar/Tur", "S1_linear"),
                           ("Moong(Green Gram)", "S1_linear"), ("Rice", "S1_linear")]:
            check(f"the selected specification for {crop} is {spec}",
                  fm["crops"][crop]["selected_spec"] == spec,
                  fm["crops"][crop]["selected_spec"])
        check("the selection method is recorded",
              "leave-one-season-out" in fm["selection_method"],
              fm["selection_method"])
        check("the validity gate is recorded",
              "positive" in fm["validity_gate"], fm["validity_gate"])
    else:
        check("forecast models artefact present", False, "forecast_models.json missing")

    fs_path = cfg.PROCESSED / "forecast_series.json"
    if fs_path.exists():
        fs = cfg.read_json(fs_path)
        check("the area baseline is 2022-23",
              fs["area_baseline_season"] == "2022-23", fs["area_baseline_season"])
        check("the aggregation is recorded as area-weighted",
              "area-weighted" in fs["aggregation"], fs["aggregation"])
        check("the measure is stated as yield per hectare",
              "yield per hectare" in fs["measure"], fs["measure"])
    else:
        check("forecast series artefact present", False, "forecast_series.json missing")

    # ---- C11 the indexed forecast chart ------------------------------------
    # The README publishes the indexed state series the chart draws.  It is
    # recomputed from the panel here, so the README and the panel cannot
    # drift apart silently.
    panel_path = cfg.PROCESSED / f"panel_v{cfg.data_version()}.parquet"
    if panel_path.exists() and fs_path.exists():
        import pandas as pd  # noqa: PLC0415

        panel = pd.read_parquet(panel_path)
        fs = cfg.read_json(fs_path)
        for crop, res in fs["crops"].items():
            ref = res["state"]["reference_yield_per_ha"]
            d = panel[panel["crop"] == crop]
            st = d.groupby("season").apply(
                lambda s: float((s["yield"] * s["area_ha"]).sum() / s["area_ha"].sum()),
                include_groups=False,
            )
            idx = {s: 100.0 * v / ref for s, v in st.items()}
            end = 100.0 * res["state"]["yield_2026_per_ha"] / ref
            # the 2026 endpoint on the indexed axis is the forecast difference
            check(f"the indexed 2026 endpoint for {crop} equals 100 + the forecast %",
                  close(end, 100.0 + res["state"]["pct_vs_reference"], 0.06),
                  f"{end:.2f} vs {100.0 + res['state']['pct_vs_reference']:.2f}")
            # every season's index must appear in the README table
            for season, value in idx.items():
                check(f"README index table has {crop} {season} = {value:.1f}",
                      f"{value:.1f}" in readme, f"{value:.1f}")
            check(f"README index table has the 2026 endpoint for {crop} = {end:.1f}",
                  f"**{end:.1f}**" in readme, f"{end:.1f}")
            # the state figure must be a state total over a state area,
            # computed on the primary panel exactly as the forecast does
            dp = panel[(panel["crop"] == crop) & panel["is_primary_panel"]]
            pooled = float(dp["production"].sum() / dp["area_ha"].sum())
            check(f"the area-weighted reference for {crop} equals the pooled ratio",
                  close(pooled, ref, 1e-3), f"{pooled:.4f} vs {ref:.4f}")

    # the report's headline and the section headings
    check("the report headline is the forecast, not a reading",
          "# Forecasting kharif yield from rainfall" in readme
          and "**Telangana, kharif 2014-15 → 2022-23, four crops, 32 districts "
              "— and a 2026 forecast.**" in readme, "")
    check("the validation section is retitled",
          "### Can rainfall predict a district's kharif yield?" in readme, "")
    check("the retired heading is gone from the report",
          "Does the weather model earn its place?" not in readme, "")

    # ---- C11 the retired sections ------------------------------------------
    index_html = (cfg.DASHBOARD / "index.html").read_text()
    app_js = (cfg.DASHBOARD / "assets" / "app.js").read_text()
    styles = (cfg.DASHBOARD / "assets" / "styles.css").read_text()
    check("the response-curve chart is retired from the page",
          "curveChart" not in index_html and "renderCurve" not in app_js, "")
    check("the 2018-19 districts table is retired from the page",
          "districtTable" not in index_html and "renderTable" not in app_js, "")
    check("the four-panel forecast grid is retired",
          "forecastGrid" not in index_html and "forecast-cell" not in styles, "")
    check("the state summary carries the 2026 and state-average columns",
          "2026" in index_html and "State avg" in index_html, "")
    check("the crop selector offers All plus the crop ticks",
          "All crops" in app_js and "forecast-tick" in app_js, "")
    check("the chart axis is indexed to the Telangana average",
          "Telangana average = 100" in app_js, "")
    check("the state line is area-weighted in the chart",
          "area-weighted" in app_js, "")

    # ---- C12 the state summary table ----------------------------------------
    # The dashboard's five-row summary must agree with the artefacts: four
    # crops plus the kharif rainfall, 2026 against the state average.
    if fs_path.exists():
        fs = cfg.read_json(fs_path)
        for crop, res in fs["crops"].items():
            st = res["state"]
            is_bales = res["unit"] == "bales/ha"
            unit_label = "M bales" if is_bales else "M t"
            m26 = st["total_2026"] / 1e6
            mavg = st["reference_total_same_area"] / 1e6
            d26 = 2 if abs(m26) >= 1 else 3
            davg = 2 if abs(mavg) >= 1 else 3
            check(f"the summary table gives the 2026 total for {crop}",
                  f"{m26:.{d26}f} {unit_label}" in readme,
                  f"{m26:.{d26}f} {unit_label}")
            check(f"the summary table gives the average total for {crop}",
                  f"{mavg:.{davg}f} {unit_label}" in readme,
                  f"{mavg:.{davg}f} {unit_label}")
            pct = st["pct_vs_reference"]
            arrow = "\u2193" if pct < 0 else "\u2191"
            check(f"the summary table gives the change for {crop}",
                  f"{arrow} {abs(pct):.1f} %" in readme
                  or f"{arrow} {abs(pct):.1f}%" in readme,
                  f"{arrow} {abs(pct):.1f}%")

    bundle_path = cfg.DASHBOARD_DATA / "bundle.js"
    if bundle_path.exists():
        raw = bundle_path.read_text()
        bundle = json.loads(raw[raw.index("{"):].rstrip().rstrip(";"))
        rs = bundle.get("rain_state") or {}
        check("the bundle carries the state mean rainfall by season",
              len(rs.get("per_season", {})) == 9, str(len(rs.get("per_season", {}))))
        check("the nine-season state-wise rainfall average is in the bundle",
              close(rs.get("avg_9season"), 848.3, 0.2), str(rs.get("avg_9season")))
        # and the README must quote it
        check("the README quotes the nine-season rainfall average",
              "848 mm" in readme, "")
        # the 2026 state mean against that base
        mk = bundle.get("marker") or {}
        if mk.get("state_mean") and rs.get("avg_9season"):
            pct = 100.0 * (mk["state_mean"] / rs["avg_9season"] - 1.0)
            check("the rainfall change against the nine-season average",
                  close(pct, -42.5, 0.2), f"{pct:.2f}")
            check("the README quotes the rainfall change",
                  "42.5 %" in readme or "42.5%" in readme, f"{pct:.1f}")
        # the 2026 map layer has its own fixed domains
        d26 = bundle.get("domains_2026") or {}
        check("the 2026 map layer has a domain for every crop",
              set(d26) == {"Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)", "Rice", "deficit"},
              str(sorted(d26)))
        for crop in ["Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)", "Rice"]:
            dom = d26[crop]["yield"]
            preds = bundle["forecast"][crop]["per_district"]
            vals = [r["predicted_2026"] for r in preds]
            check(f"the 2026 yield domain for {crop} covers its predictions",
                  close(dom[0], min(vals), 1e-3) and close(dom[1], max(vals), 1e-3),
                  f"{dom} vs {min(vals)}, {max(vals)}")

    # ---- C13 the retired sections -------------------------------------------
    # The page no longer carries the districts table, the disclosure list or
    # the boxed 2026 disclaimer.  The README keeps the disclosures, so the
    # report of record still carries every one of them.
    index_html = (cfg.DASHBOARD / "index.html").read_text()
    app_js = (cfg.DASHBOARD / "assets" / "app.js").read_text()
    styles = (cfg.DASHBOARD / "assets" / "styles.css").read_text()
    check("the districts table is retired from the page",
          'id="forecastTable"' not in index_html
          and "renderForecastTable" not in app_js
          and "els.forecastTableBody" not in app_js, "")
    check("the disclosure footer is retired from the page",
          "disclosureList" not in index_html and "populateDisclosures" not in app_js
          and "What this is not" not in index_html, "")
    check("the 2026 disclaimer box is retired from the page",
          "markerDisclaimer" not in index_html and "markerDisclaimer" not in app_js, "")
    check("the retired styles are gone",
          "#forecastTable" not in styles and ".disclosures" not in styles
          and ".colophon" not in styles, "")
    check("the page still labels 2026 as a prediction",
          "2026-27 (prediction)" in app_js
          and "2026-27 · prediction" in app_js
          and "(prediction)" in app_js, "")

    # ---- C14 the two retired page sections, and the new masthead -----------
    check("the model-comparison section is retired from the page",
          "Does the weather model earn its place?" not in index_html
          and "renderStats" not in app_js
          and "els.stats" not in app_js
          and "region--stats" not in styles, "")
    check("the window-sensitivity section is retired from the page",
          "Does the rainfall optimum depend on the season window?" not in index_html
          and "renderWindowPanel" not in app_js
          and "region--window" not in styles
          and ".window-table" not in styles, "")
    check("the bundle no longer ships the window panel",
          "window_sensitivity" not in bundle if bundle_path.exists() else True, "")
    check("the headline is one line",
          "Forecasting kharif yield from rainfall and 2026 prediction" in index_html, "")
    check("the standfirst names the scope, the crops, the source and the model",
          "32 districts" in index_html
          and "Kharif 2014-15" in index_html
          and "Cotton (lint), arhar/tur, moong (green gram), rice" in index_html
          and "Agrometeorology" in index_html
          and "Open-Meteo archive API" in index_html
          and "least squares with district and year fixed effects" in index_html, "")
    check("the model readout panel is retired from the page",
          'id="modelFacts"' not in index_html
          and "renderModelFacts" not in app_js
          and "forecastFacts" not in app_js, "")
    check("the reading defaults to the rice prediction",
          'DEFAULT_READING_CROP = "Rice"' in app_js, "")
    check("the foot is headed items, not one paragraph",
          'footItem("How to read the axis"' in app_js
          and 'footItem("The state line"' in app_js
          and 'footItemWide("The 2026 segment"' in app_js
          and 'footItem("How well the model does"' in app_js, "")
    check("the skill scores are listed one per crop",
          "forecast-foot__skill" in app_js, "")
    check("the hover label is lifted off the plot",
          "drop-shadow" in styles
          and ".hoverlayer g.hovertext > path" in styles, "")
    check("the empty-state prompt is retired",
          "forecastDetailEmpty" not in index_html
          and "Select a point in the chart above" not in index_html, "")
    check("the yield-per-year chart is named",
          "Yield per year, and the 2026 prediction" in index_html, "")
    cfg_block = app_js[app_js.index("var PLOT_CONFIG"):
                       app_js.index("};", app_js.index("var PLOT_CONFIG"))]
    check("the hover label is styled in the LAYOUT, not the config",
          "hoverlabel: HOVER_LABEL" in app_js
          and "var HOVER_LABEL = {" in app_js
          and "hoverlabel" not in cfg_block, "")


    # ---- the disclosure set: the bundle and the report must agree -----------
    if bundle_path.exists():
        raw = bundle_path.read_text()
        b = json.loads(raw[raw.index("{"):].rstrip().rstrip(";"))
        disc = b["meta"].get("disclosures") or {}
        check("the bundle ships the 15 mandatory disclosures",
              len(disc) == 15, str(len(disc)))
        # the report of record must carry every one of them
        plain = readme.replace("**", "")
        # every disclosure the bundle ships must be carried by the report,
        # under its own heading.  The map is written out here so that the
        # link between the record and the report is auditable rather than
        # inferred from a string comparison.
        headings = {
            "reanalysis": "Reanalysis, not observation",
            "convective": "Convective rainfall bias",
            "confound": "No irrigation, soil, or input data",
            "aggregates": "District aggregates, not farm-level",
            "boundary": "Boundary discontinuity",
            "sowing": "Sowing window",
            "agency": "DES agency discontinuity",
            "cotton": "Cotton is reported in bales",
            "sample": "Small sample per crop",
            "not_forecast": "2026 is a model prediction, not a validated forecast",
            "forecast_method": "Each crop is forecast by its own specification",
            "forecast_area": "2026 planted area does not exist",
            "forecast_specimens": "No prediction interval is claimed",
            "attribution": "Attribution",
            "percentiles": "Rule-based percentile bands",
        }
        check("the bundle ships exactly the 15 known disclosures",
              set(disc) == set(headings), str(sorted(set(disc) ^ set(headings))))
        for key, heading in headings.items():
            check(f"the report carries the disclosure '{key}'",
                  heading in plain, heading[:50])
        for phrase in [
            "2026 is a model prediction",
            "2026 planted area does not exist",
            "No prediction interval is claimed",
            "Each crop is forecast by its own specification",
        ]:
            check(f"the report carries the forecast disclosure: {phrase[:38]}",
                  phrase in plain, phrase)

    # ---- §7 the twelve disclosures ----------------------------------------
    for phrase in [
        "Reanalysis, not observation", "Convective rainfall bias",
        "No irrigation, soil, or input data", "District aggregates, not farm-level",
        "Boundary discontinuity", "Sowing window", "DES agency discontinuity",
        "reported in bales", "Small sample per crop", "2026 is a model prediction",
        "Attribution", "Rule-based percentile bands",
    ]:
        check(f"disclosure present: {phrase}", phrase in readme)

    # ---- report ------------------------------------------------------------
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print(f"  FAIL  {name}  (artefact says: {detail})")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} README numbers verified against the artefacts")
    if failed:
        print(f"{len(failed)} mismatch(es) - the README and the artefacts disagree")
        sys.exit(1)


if __name__ == "__main__":
    main()
