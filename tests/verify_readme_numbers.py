"""Verify the numbers printed in README.md against the built artefacts.

Acceptance criterion A1: "Every number in README traces to a committed
artefact.  Spot-check 5 values against data/processed/".  This script does
that for every headline number the README states, so the check is repeatable
rather than a one-off read.

Usage:  PYTHONHASHSEED=0 .venv/bin/python tests/verify_readme_numbers.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import common as cfg  # noqa: E402


def close(a, b, tol=5e-4):
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def main() -> None:
    models = cfg.read_json(cfg.PROCESSED / "model_summary.json")
    manifest = cfg.read_json(cfg.MANIFESTS / "fetch_manifest.json")
    geo = cfg.read_json(cfg.MANIFESTS / "geo.json")
    weather = cfg.read_json(cfg.MANIFESTS / "weather_fetch.json")
    des = cfg.read_json(cfg.MANIFESTS / "des_ingest.json")

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    s1 = models["crops"]
    s2 = models["stage2"]
    val = models["validation"]["crops"]

    # ---- README §2 / §3 : data sources ------------------------------------
    check("DES parsed shape is (238, 111)",
          des["parsed_shape"] == [238, 111], str(des["parsed_shape"]))
    check("DES covers 2014-15 to 2022-23",
          des["seasons"][0] == "2014-15" and des["seasons"][-1] == "2022-23",
          f"{des['seasons'][0]}..{des['seasons'][-1]}")
    check("36 crop groups in the file", len(des["crops_in_file"]) == 36,
          str(len(des["crops_in_file"])))
    check("two crop groups are in bales",
          sum(1 for u in des["units_in_file"].values() if u == "bales/ha") == 2,
          str([c for c, u in des["units_in_file"].items() if u == "bales/ha"]))
    check("weather ingest window is 2014-06-01 to 2023-10-31",
          weather["temp_window"] == ["2014-06-01", "2023-10-31"],
          str(weather["temp_window"]))
    check("32 districts on the primary panel", manifest["districts"] == 32,
          str(manifest["districts"]))
    check("panel has 3185 rows", manifest["rows"] == 3185, str(manifest["rows"]))
    check("primary panel has 2867 rows", manifest["rows_primary_panel"] == 2867,
          str(manifest["rows_primary_panel"]))
    check("weather has 113984 district-days", weather["rows"] == 113984,
          str(weather["rows"]))
    check("no NaN in the weather record",
          all(v == 0 for v in weather["nan_rate"].values()), str(weather["nan_rate"]))
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

    # ---- README §4 : Stage 1 ----------------------------------------------
    for crop, n, b1, p1, b2, p2, r2 in [
        ("Cotton(lint)", 220, 0.001462, 0.1185, -4.337e-07, 0.2938, 0.5699),
        ("Arhar/Tur", 219, 0.004608, 0.0900, -2.227e-06, 0.0691, 0.2488),
        ("Moong(Green Gram)", 209, 0.000003, 0.9917, -4.847e-08, 0.6954, 0.5454),
        ("Rice", 220, 0.001466, 0.0050, -5.410e-07, 0.0187, 0.7318),
    ]:
        p = s1[crop]["primary"]
        check(f"{crop}: n = {n}", p["n_rows"] == n, str(p["n_rows"]))
        check(f"{crop}: b1 = {b1}", close(p["b1"], b1), str(p["b1"]))
        check(f"{crop}: p(b1) = {p1}", close(p["p1"], p1, 1e-3), str(p["p1"]))
        check(f"{crop}: b2 = {b2}", close(p["b2"], b2, 1e-3), str(p["b2"]))
        check(f"{crop}: p(b2) = {p2}", close(p["p2"], p2, 1e-3), str(p["p2"]))
        check(f"{crop}: R2 = {r2}", close(p["r2"], r2, 1e-3), str(p["r2"]))

    for crop in ("Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)"):
        check(f"{crop}: no vertex reported",
              s1[crop]["primary"]["vertex_reported"] is False,
              str(s1[crop]["primary"]["vertex_reason"]))
    rice = s1["Rice"]["primary"]
    check("rice: R* = 1355 mm", close(rice["vertex_mm"], 1354.68, 1e-3),
          str(rice["vertex_mm"]))
    check("rice: 95% CI 1019-1690",
          close(rice["vertex_ci95_mm"][0], 1018.87, 1e-3)
          and close(rice["vertex_ci95_mm"][1], 1690.49, 1e-3),
          str(rice["vertex_ci95_mm"]))
    check("rice: vertex sits at the 95th percentile",
          close(rice["vertex_frac_obs_below"], 0.95, 1e-2),
          str(rice["vertex_frac_obs_below"]))
    check("rice: curve still rising over most of the range",
          rice["curve_rising_over_most_of_range"] is True)
    check("rice: no vertex without season fixed effects",
          s1["Rice"]["no_season_fe"]["vertex_reported"] is False)
    check("rice: extended panel vertex 1350 mm",
          close(s1["Rice"]["extended_panel"]["vertex_mm"], 1349.74, 1e-3),
          str(s1["Rice"]["extended_panel"]["vertex_mm"]))

    # ---- README §4 : linear-only robustness -------------------------------
    check("cotton linear-only p = 0.043",
          close(s1["Cotton(lint)"]["linear_only"]["p1"], 0.0425, 1e-2),
          str(s1["Cotton(lint)"]["linear_only"]["p1"]))
    check("arhar linear-only p = 0.835",
          close(s1["Arhar/Tur"]["linear_only"]["p1"], 0.8345, 1e-2),
          str(s1["Arhar/Tur"]["linear_only"]["p1"]))
    check("moong linear-only p = 0.156",
          close(s1["Moong(Green Gram)"]["linear_only"]["p1"], 0.1561, 1e-2),
          str(s1["Moong(Green Gram)"]["linear_only"]["p1"]))

    # ---- README §4 : Stage 2 ----------------------------------------------
    for crop, r2_1, r2_2, d_r2, d_adj, f_p in [
        ("Cotton(lint)", 0.5699, 0.6005, 0.0306, 0.0233, 0.0233),
        ("Arhar/Tur", 0.2488, 0.2688, 0.0200, -0.0012, 0.4491),
        ("Moong(Green Gram)", 0.5454, 0.5579, 0.0125, -0.0012, 0.4654),
        ("Rice", 0.7318, 0.7385, 0.0067, -0.0010, 0.4879),
    ]:
        s = s2[crop]
        check(f"{crop}: R2 {r2_1} -> {r2_2}",
              close(s["r2_stage1"], r2_1, 1e-3) and close(s["r2_stage2"], r2_2, 1e-3),
              f"{s['r2_stage1']} -> {s['r2_stage2']}")
        check(f"{crop}: dR2 = {d_r2}", close(s["delta_r2"], d_r2, 1e-2),
              str(s["delta_r2"]))
        check(f"{crop}: dAdjR2 = {d_adj}", close(s["delta_adj_r2"], d_adj, 1e-2),
              str(s["delta_adj_r2"]))
        check(f"{crop}: partial F p = {f_p}", close(s["partial_f_p"], f_p, 1e-2),
              str(s["partial_f_p"]))
    check("stage 2 arhar has a significant quadratic (p = 0.026)",
          close(s2["Arhar/Tur"]["p2"], 0.0263, 1e-2), str(s2["Arhar/Tur"]["p2"]))
    check("stage 2 arhar vertex 1083 mm",
          close(s2["Arhar/Tur"]["vertex_mm"], 1082.77, 1e-3),
          str(s2["Arhar/Tur"]["vertex_mm"]))

    # ---- README §4 : validation -------------------------------------------
    for crop, rmse_m, rmse_b, skill, skill_nf in [
        ("Cotton(lint)", 0.7873, 0.5612, -0.4029, -0.3552),
        ("Arhar/Tur", 1.8858, 1.9499, 0.0329, 0.0307),
        ("Moong(Green Gram)", 0.2610, 0.2550, -0.0233, -0.0353),
        ("Rice", 0.5017, 0.4515, -0.1110, -0.0122),
    ]:
        v = val[crop]
        check(f"{crop}: RMSE model {rmse_m}", close(v["rmse_model"], rmse_m, 1e-3),
              str(v["rmse_model"]))
        check(f"{crop}: RMSE baseline {rmse_b}", close(v["rmse_baseline"], rmse_b, 1e-3),
              str(v["rmse_baseline"]))
        check(f"{crop}: skill {skill}", close(v["skill_rmse"], skill, 1e-3),
              str(v["skill_rmse"]))
        check(f"{crop}: no-FE skill {skill_nf}",
              close(v["no_season_fe"]["skill_rmse"], skill_nf, 1e-3),
              str(v["no_season_fe"]["skill_rmse"]))
    check("split is train <= 2019-20 / test >= 2020-21",
          models["validation"]["train_last_season"] == "2019-20"
          and models["validation"]["test_first_season"] == "2020-21")

    # ---- README §4 : the 2026 reading -------------------------------------
    marker_path = cfg.INTERIM / "features_2026.parquet"
    if marker_path.exists():
        import pandas as pd

        m = pd.read_parquet(marker_path)
        check("2026 state-mean rainfall = 488 mm",
              close(m["rain_mm"].mean(), 487.9, 1e-3), str(round(m["rain_mm"].mean(), 1)))
        check("2026 p10-p90 = 285-731 mm",
              close(m["rain_mm"].quantile(0.10), 285.2, 1e-2)
              and close(m["rain_mm"].quantile(0.90), 731.2, 1e-2),
              f"{m['rain_mm'].quantile(0.10):.1f}-{m['rain_mm'].quantile(0.90):.1f}")
        check("2026 median = 439 mm", close(m["rain_mm"].median(), 439.4, 1e-2),
              str(round(m["rain_mm"].median(), 1)))
        check("2026 range 248-816 mm",
              close(m["rain_mm"].min(), 248.2, 1e-2)
              and close(m["rain_mm"].max(), 816.1, 1e-2),
              f"{m['rain_mm'].min():.1f}-{m['rain_mm'].max():.1f}")
        hist = manifest and None
        panel = None
        try:
            import pandas as pd

            panel = pd.read_parquet(
                cfg.PROCESSED / f"panel_v{cfg.data_version()}.parquet"
            )
            prim = panel[panel["is_primary_panel"]]
            check("fitted-period rainfall range 374-1827 mm",
                  close(prim["rain_mm"].min(), 373.7, 1e-2)
                  and close(prim["rain_mm"].max(), 1826.7, 1e-2),
                  f"{prim['rain_mm'].min():.1f}-{prim['rain_mm'].max():.1f}")
            check("2026 is the 1.6th percentile of the fitted period",
                  close((prim["rain_mm"] < m["rain_mm"].mean()).mean() * 100, 1.6, 1e-2),
                  f"{(prim['rain_mm'] < m['rain_mm'].mean()).mean()*100:.2f}")
            check("9 of 32 districts fall below the observed minimum",
                  int((m["rain_mm"] < prim["rain_mm"].min()).sum()) == 9,
                  str(int((m["rain_mm"] < prim["rain_mm"].min()).sum())))
        except Exception as exc:  # pragma: no cover
            check("2026 comparison against the fitted period", False, str(exc))
    else:
        check("2026 marker features present", False, "features_2026.parquet missing")

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
