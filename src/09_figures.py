"""Step 09 - Static figures F1-F4.

F1  response curve   one row per crop, Stage 1 next to Stage 2, vertex
                     annotated, 2026 rainfall as a dashed marker
F2  time series     stacked, shared x-axis, p10-p90 bands, NO dual axis
F3  validation      model vs baseline RMSE by crop, chronological test period
F4  choropleth      yield anomaly % by district, RdYlBu, fixed domain

Colour system (SRS §7.1):
  YlOrRd  sequential, drought / rainfall deficit
  RdYlBu  diverging, yield anomaly, zero pinned to the exact midpoint
  jet / rainbow / hsv and red-green pairings are prohibited.

Authority: plan/SRS.md §7.1, §7.3 ; plan/GUIDE.md Step 10.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize
from matplotlib.patches import Polygon as MplPolygon

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

VERSION = cfg.data_version()
DPI = 200

plt.rcParams.update(
    {
        "figure.dpi": 110,
        "savefig.dpi": DPI,
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linestyle": ":",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
    }
)

PLOT_CROPS = ["Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)", "Rice"]
CROP_SHORT = {
    "Cotton(lint)": "Cotton (lint)",
    "Arhar/Tur)": "Arhar / Tur",
    "Moong(Green Gram)": "Moong (green gram)",
    "Rice": "Rice",
}


def crop_label(crop: str) -> str:
    return {
        "Cotton(lint)": "Cotton (lint)",
        "Arhar/Tur": "Arhar / Tur",
        "Moong(Green Gram)": "Moong (green gram)",
        "Rice": "Rice",
    }.get(crop, crop)


def load_marker():
    """2026 marker features, if the marker window has been ingested."""
    path = cfg.INTERIM / "features_2026.parquet"
    if path.exists():
        m = pd.read_parquet(path)
        return m
    return None


# --------------------------------------------------------------------------- #
# F1 - response curve
# --------------------------------------------------------------------------- #
def figure_f1(panel, summary, marker):
    stage1 = summary["crops"]
    stage2 = summary.get("stage2", {})
    fig, axes = plt.subplots(
        len(PLOT_CROPS), 2, figsize=(11.5, 3.1 * len(PLOT_CROPS)), sharex="col"
    )

    marker_mean = marker_rain_band(marker)

    for r, crop in enumerate(PLOT_CROPS):
        d = panel[(panel["crop"] == crop) & panel["is_primary_panel"]]
        if d.empty:
            continue
        s1 = stage1.get(crop, {}).get("primary", {})
        s2 = stage2.get(crop, {})

        for c, (title, coef) in enumerate(
            [
                ("Stage 1 · rainfall quadratic", s1),
                ("Stage 2 · + dry-spell, heat, VPD", s2),
            ]
        ):
            ax = axes[r, c]
            if not coef:
                ax.set_visible(False)
                continue

            b1 = float(coef["b1"])
            b2 = float(coef["b2"])

            ax.scatter(
                d["rain_mm"], d["yield"], s=16, alpha=0.55,
                color=cfg.C_CURVE, edgecolor="none", zorder=2,
                label="district-season observations",
            )

            # x limits: the 2026 band is shown even when it falls outside the
            # fitted range, so the reader can see how far outside it sits
            x_lo = float(d["rain_mm"].min())
            x_hi = float(d["rain_mm"].max())
            if marker_mean is not None:
                x_lo = min(x_lo, marker_mean[0])
                x_hi = max(x_hi, marker_mean[1])
            ax.set_xlim(x_lo, x_hi)

            # The curve is the MEAN-CENTRED partial effect of rainfall:
            #   y(R) = mean(yhat) + b1*(R - Rbar) + b2*(R^2 - R2bar)
            # i.e. the average fitted yield with the district and season
            # fixed effects held at their sample means, as rainfall varies.
            # Plotting the raw intercept instead would show the reference
            # district in the reference season, which is not a curve anybody
            # can read.
            y0 = float(coef.get("mean_fitted", 0.0))
            rbar = float(coef.get("rain_mean_mm", d["rain_mm"].mean()))
            r2bar = float(coef.get("rain_sq_mean", (d["rain_mm"] ** 2).mean()))
            x = np.linspace(d["rain_mm"].min(), d["rain_mm"].max(), 200)
            y = y0 + b1 * (x - rbar) + b2 * (x**2 - r2bar)
            ax.plot(x, y, color=cfg.C_CURVE, lw=1.8, zorder=3, label="fitted quadratic")

            # y limits: robust to single extreme observations, which are
            # annotated rather than silently dropped
            lo, hi = np.nanpercentile(d["yield"], [0.5, 99.5])
            pad = 0.18 * (hi - lo)
            ax.set_ylim(lo - pad, hi + pad)
            clipped = d[d["yield"] > hi + pad].sort_values("yield", ascending=False)
            if len(clipped):
                note = "\n".join(
                    f"{r['district_label']} {r['season']}: {r['yield']:.1f}"
                    for _, r in clipped.head(3).iterrows()
                )
                ax.text(
                    0.985, 0.03,
                    f"{len(clipped)} observation(s) above the axis:\n{note}",
                    transform=ax.transAxes, ha="right", va="bottom", fontsize=6.5,
                    color="#555555",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cccccc"),
                )

            # vertex
            vertex = coef.get("vertex_mm")
            if vertex and coef.get("vertex_reported"):
                yv = y0 + b1 * (vertex - rbar) + b2 * (vertex**2 - r2bar)
                ax.scatter([vertex], [yv], s=70, color=cfg.C_CURVE, zorder=5,
                           edgecolor="white", linewidth=1.2)
                lo, hi = coef.get("vertex_ci95_mm", [None, None])
                note = f"R* = {vertex:,.0f} mm"
                if lo is not None:
                    note += f"\n95% CI {lo:,.0f}–{hi:,.0f}"
                ax.annotate(
                    note, xy=(vertex, yv), xytext=(-8, 26),
                    textcoords="offset points", ha="right", fontsize=8,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#999999", alpha=0.9),
                )
            else:
                reason = coef.get("vertex_reason", "quadratic term not significant")
                ax.text(
                    0.985, 0.96, f"no significant inverted-U\n({reason})",
                    transform=ax.transAxes, va="top", ha="right", fontsize=7.5,
                    bbox=dict(boxstyle="round,pad=0.3", fc="#fff8e1", ec="#c9a227", alpha=0.95),
                )

            # 2026 rainfall marker
            if marker_mean is not None:
                lo26, hi26, mean26 = marker_mean
                ax.axvspan(lo26, hi26, color=cfg.C_MARKER_2026, alpha=0.07, zorder=1)
                ax.axvline(mean26, color=cfg.C_MARKER_2026, ls="--", lw=1.4, zorder=4)
                if c == 0:
                    y26 = y0 + b1 * (mean26 - rbar) + b2 * (mean26**2 - r2bar)
                    ax.scatter([mean26], [y26], s=60, facecolor="none",
                               edgecolor=cfg.C_MARKER_2026, lw=1.6, zorder=6)
                    ax.annotate(
                        f"2026 observed rainfall\n{mean26:,.0f} mm (state mean)",
                        xy=(mean26, y26), xytext=(6, -34), textcoords="offset points",
                        fontsize=7.5, color=cfg.C_MARKER_2026,
                    )

            unit = d["unit"].iloc[0]
            ax.set_ylabel(f"yield ({unit})")
            if c == 0:
                ax.set_title(f"{crop_label(crop)}\n{title}", loc="left", fontsize=9.5)
            else:
                ax.set_title(title, loc="left", fontsize=9.5)
            if r == len(PLOT_CROPS) - 1:
                ax.set_xlabel("kharif rainfall, 1 Jun – 30 Sep (mm)")

    txt = (
        "Response curve fitted on observed kharif yields (district + season fixed effects). "
        "2026 rainfall is ERA5 observed; any implied yield is a reading of the fitted curve, "
        "not a validated forecast — the extrapolation gap is 3+ years. "
        "ERA5 is a 0.25° reanalysis, not station gauge data. "
        "Effects are rainfall's marginal association conditional on all other factors being average."
    )
    fig.text(0.005, 0.002, txt, fontsize=6.6, color="#444444", va="bottom", wrap=True)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    out = cfg.FIGURES / "f1_response_curve.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log(f"  wrote {out}")


def marker_rain_band(marker):
    if marker is None:
        return None
    vals = marker["rain_mm"]
    return (float(vals.quantile(0.10)), float(vals.quantile(0.90)), float(vals.mean()))


# --------------------------------------------------------------------------- #
# F2 - time series
# --------------------------------------------------------------------------- #
def figure_f2(panel):
    crop = "Cotton(lint)"
    d = panel[(panel["crop"] == crop) & panel["is_primary_panel"]]
    g = d.groupby("season")
    seasons = sorted(d["season"].unique())
    x = np.arange(len(seasons))

    rain_p10 = g["rain_mm"].quantile(0.10).reindex(seasons).to_numpy()
    rain_p50 = g["rain_mm"].median().reindex(seasons).to_numpy()
    rain_p90 = g["rain_mm"].quantile(0.90).reindex(seasons).to_numpy()
    y_p10 = g["yield"].quantile(0.10).reindex(seasons).to_numpy()
    y_p50 = g["yield"].median().reindex(seasons).to_numpy()
    y_p90 = g["yield"].quantile(0.90).reindex(seasons).to_numpy()

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9.2, 6.0), sharex=True, gridspec_kw={"height_ratios": [1, 1]}
    )

    ax1.fill_between(x, rain_p10, rain_p90, color=cfg.C_RAIN, alpha=0.18,
                     label="p10–p90 across districts")
    ax1.plot(x, rain_p50, color=cfg.C_RAIN, lw=2.0, marker="o", ms=4,
             label="state median")
    ax1.set_ylabel("kharif rainfall (mm)")
    ax1.set_title(
        f"Kharif rainfall and cotton yield, Telangana {seasons[0]} – {seasons[-1]}\n"
        "post-2016 districts · ERA5 reanalysis (0.25°)",
        loc="left",
    )
    ax1.legend(frameon=False, fontsize=8, loc="upper left")

    ax2.fill_between(x, y_p10, y_p90, color=cfg.C_YIELD, alpha=0.18)
    ax2.plot(x, y_p50, color=cfg.C_YIELD, lw=2.0, marker="o", ms=4, label="state median")
    ax2.set_ylabel("cotton lint yield (bales/ha)")
    ax2.set_xlabel("kharif season (Jun – Sep)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(seasons, rotation=45, ha="right")

    txt = (
        "Two stacked panels sharing one x-axis; no dual axis is used. "
        "Bands are rule-based percentiles, descriptive, not inferential — no confidence intervals are claimed. "
        "Jun–Sep is the sowing window, not the full growing season."
    )
    fig.text(0.005, 0.002, txt, fontsize=6.6, color="#444444", va="bottom", wrap=True)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = cfg.FIGURES / "f2_timeseries.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log(f"  wrote {out}")


# --------------------------------------------------------------------------- #
# F3 - validation
# --------------------------------------------------------------------------- #
def figure_f3(summary):
    val = summary.get("validation", {}).get("crops", {})
    crops = [c for c in PLOT_CROPS if c in val]
    if not crops:
        return
    x = np.arange(len(crops))
    w = 0.26

    rmse_model = [val[c]["rmse_model"] for c in crops]
    rmse_base = [val[c]["rmse_baseline"] for c in crops]
    rmse_model_nf = [val[c]["no_season_fe"]["rmse_model"] for c in crops]
    skill = [val[c]["skill_rmse"] for c in crops]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.0),
                                   gridspec_kw={"width_ratios": [1.35, 1]})

    ax1.bar(x - w, rmse_model, w, color=cfg.C_CURVE, label="model (with season FE)")
    ax1.bar(x, rmse_model_nf, w, color="#9ecae1", label="model (no season FE)")
    ax1.bar(x + w, rmse_base, w, color="#bdbdbd", label="district-crop median baseline")
    ax1.set_xticks(x)
    ax1.set_xticklabels([crop_label(c) for c in crops], rotation=20, ha="right")
    ax1.set_ylabel("out-of-sample RMSE")
    ax1.set_title(
        "Out-of-sample RMSE, chronological test period\n"
        f"train ≤ {summary['validation']['train_last_season']}  ·  "
        f"test ≥ {summary['validation']['test_first_season']}",
        loc="left",
    )
    ax1.legend(frameon=False, fontsize=8)

    colors = ["#2c7fb8" if s > 0 else "#d95f0e" for s in skill]
    ax2.barh(x, skill, color=colors, height=0.5)
    ax2.axvline(0, color="#333333", lw=1.0)
    ax2.set_yticks(x)
    ax2.set_yticklabels([crop_label(c) for c in crops])
    ax2.invert_yaxis()
    ax2.set_xlabel("skill = 1 − RMSE_model / RMSE_baseline")
    ax2.set_title("Skill against the median baseline", loc="left")
    for i, s in enumerate(skill):
        if abs(s) > 0.12:
            # long bar: put the value inside it so it cannot collide with the
            # axis labels
            ax2.text(s * 0.97, i, f"{s:+.3f}", va="center",
                     ha="right" if s >= 0 else "left", fontsize=8, color="white")
        else:
            ax2.text(s + (0.02 if s >= 0 else -0.02), i, f"{s:+.3f}",
                     va="center", ha="left" if s >= 0 else "right", fontsize=8)

    txt = (
        "A negative skill score means the weather-only model does not beat the "
        "district-crop median in the test period; that is a reportable result, not a failure. "
        "The baseline median is computed on the train period only."
    )
    fig.text(0.005, 0.002, txt, fontsize=6.6, color="#444444", va="bottom", wrap=True)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out = cfg.FIGURES / "f3_validation.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log(f"  wrote {out}")


# --------------------------------------------------------------------------- #
# F4 - choropleth
# --------------------------------------------------------------------------- #
def figure_f4(panel, year="2022-23", crop="Cotton(lint)"):
    geo = json.loads((cfg.GEO / "districts.geojson").read_text())
    centroids = pd.read_csv(cfg.GEO / "districts.csv").drop_duplicates("district_slug")
    centroid_map = dict(zip(centroids["district_slug"], zip(centroids["lat"], centroids["lon"])))

    d = panel[
        (panel["crop"] == crop)
        & (panel["season"] == year)
        & panel["is_primary_panel"]
    ].set_index("district_slug")

    values = d["yield_anom_pct"].dropna()
    if values.empty:
        log(f"  F4: no data for {crop} {year}")
        return
    lim = float(max(abs(values.min()), abs(values.max())))
    lim = max(lim, 10.0)
    norm = Normalize(vmin=-lim, vmax=lim)          # zero -> exact midpoint
    # RdYlBu reversed: the SRS fixes the semantics as blue = below normal,
    # cream = normal, red = above normal.
    cmap = plt.get_cmap(cfg.CMAP_ANOM).reversed()

    fig, ax = plt.subplots(figsize=(9.0, 8.0))
    for feat in geo["features"]:
        slug = feat["properties"]["slug"]
        no_data = feat["properties"].get("no_data", False)
        geom = feat["geometry"]
        rings = (
            [geom["coordinates"][0]]
            if geom["type"] == "Polygon"
            else [poly[0] for poly in geom["coordinates"]]
        )
        for ring in rings:
            arr = np.asarray(ring, dtype=float)
            poly = MplPolygon(
                arr,
                closed=True,
                facecolor=(
                    cmap(norm(values[slug]))
                    if (slug and slug in values.index)
                    else "#eeeeee"
                ),
                edgecolor="#ffffff",
                linewidth=0.9,
            )
            ax.add_patch(poly)
        if slug and slug in values.index:
            lat, lon = centroid_map[slug]
            ax.text(lon, lat, f"{values[slug]:+.0f}", ha="center", va="center",
                    fontsize=6.8, color="#111111")
        elif no_data:
            arr = np.asarray(rings[0], dtype=float)
            ax.text(arr[:, 0].mean(), arr[:, 1].mean(), "no data",
                    ha="center", va="center", fontsize=6.5, color="#777777")

    ax.set_xlim(77.0, 80.9)
    ax.set_ylim(15.6, 20.1)
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(
        f"{crop_label(crop)} yield anomaly (%), {year}\n"
        f"post-2016 districts · colormap {cfg.CMAP_ANOM} (diverging, zero at the midpoint)",
        loc="left",
    )
    ax.grid(False)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("yield anomaly (%)   (blue = below normal, red = above normal)")

    txt = (
        "District aggregates, not farm-level. Absolute yield across Telangana is dominated by soil "
        "and irrigation; the anomaly is the risk view. Grey districts have no observation in this "
        "season (Hyderabad is absent from the delivered DES file). ERA5 rainfall is a 0.25° reanalysis."
    )
    fig.text(0.005, 0.002, txt, fontsize=6.6, color="#444444", va="bottom", wrap=True)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = cfg.FIGURES / "f4_choropleth.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log(f"  wrote {out}")


def main() -> None:
    cfg.check_determinism()
    log("Step 09: static figures")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    summary = cfg.read_json(cfg.PROCESSED / "model_summary.json")
    marker = load_marker()
    if marker is None:
        log("  2026 marker features not present yet - F1 drawn without the 2026 marker")

    figure_f1(panel, summary, marker)
    figure_f2(panel)
    figure_f3(summary)
    figure_f4(panel)


if __name__ == "__main__":
    main()
