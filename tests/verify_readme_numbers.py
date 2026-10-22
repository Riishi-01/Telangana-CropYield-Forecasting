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
          s1["Rice"]["no_season_fe"]["vertex_reported"] is False)
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
              close(v["no_season_fe"]["skill_rmse"], skill_nf, 1e-2),
              str(v["no_season_fe"]["skill_rmse"]))
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

    # ---- §7 the twelve disclosures ----------------------------------------
    for phrase in [
        "Reanalysis, not observation", "Convective rainfall bias",
        "No irrigation, soil, or input data", "District aggregates, not farm-level",
        "Boundary discontinuity", "Sowing window", "DES agency discontinuity",
        "reported in bales", "Small sample per crop", "2026 is not forecast",
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
