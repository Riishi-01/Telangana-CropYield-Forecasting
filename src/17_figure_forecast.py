"""Figures F6 and F7 - the 2026 forecast.

F6  figures/f6_forecast.png       the single indexed chart, as the dashboard
                                  draws it: four crops on one axis, each
                                  indexed to its own Telangana average, with
                                  2026 as a dashed segment.
F7  figures/f7_forecast_panels.png  the four-panel small multiples in each
                                  crop's OWN unit (bales/ha or t/ha), for
                                  reading one crop at a time.

Both charts draw the same two things: the observed seasons, and 2026 as a
DASHED segment to the predicted state yield/area, with the point estimate
marked as a diamond.

THE INDEX.  Cotton is measured in bales per hectare and the other three in
tonnes, so a single chart cannot carry a raw axis for all four.  Each crop is
indexed to its own Telangana average over the fitted period (2016-17 -
2022-23 = 100) - the same area-weighted reference the forecast table uses -
so the 2026 endpoint reads directly as the forecast difference.

THE STATE LINE IS AREA-WEIGHTED: sum(yield x area) / sum(area) over the
districts reporting in that season.  The unweighted mean of district yields
is not used, and the median is not either: the area-weighted state figure is
a state total divided by a state area, so it is the same quantity on both
sides of the 2016 reorganisation, while the district-level medians are not.

The x axis is CATEGORICAL: the nine observed seasons, then 2026 as its own
final step.  A continuous axis would place 2026 to the LEFT of the record,
because its rainfall (488 mm state mean) is below every fitted observation,
and that reads as "before 2014" rather than "a season that has not happened
yet".

The y range comes from the state line and the 2026 prediction, not from the
raw points: one delivered observation (arhar, Mulugu 2019-20) is 22.85 t/ha
against a district norm of 0.62-0.91, and letting it set the axis flattens
the chart to a line.  The point is still drawn - it is a delivered value - it
just does not get to decide the scale.

The two pre-2016 seasons are 9 undivided parent districts and 2016-17 onward
are the 32 post-reorganisation districts.  The boundary is marked, because
the district-level points on the two sides are not the same units.

Authority: plan/SRS.md §5.6 ; plan/IMPROVEMENT_PLAN.md P3-12, P4-15 ;
plan/ERRATA.md C11.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

VERSION = cfg.data_version()


def state_series(d: pd.DataFrame) -> pd.Series:
    """The area-weighted state yield per hectare for each season."""
    g = d.groupby("season").apply(
        lambda s: float((s["yield"] * s["area_ha"]).sum() / s["area_ha"].sum()),
        include_groups=False,
    )
    return g


def style_axis(ax) -> None:
    ax.grid(axis="y", color="#e6e2d8", lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d9d4c8")
    ax.tick_params(labelsize=7.5, colors="#6d7481")


def figure_f6(panel: pd.DataFrame, fs: dict) -> None:
    """The single indexed chart: four crops on one axis."""
    log("  F6: the single indexed forecast chart")

    seasons = sorted(panel["season"].unique())
    x_axis = seasons + ["2026"]
    x_index = {s: i for i, s in enumerate(x_axis)}
    boundary = x_index[cfg.PRIMARY_PANEL_START] - 0.5

    crops = [c for c in cfg.TARGET_CROPS if c in fs["crops"]]
    fig, ax = plt.subplots(figsize=(11.5, 5.4))

    scale_lo, scale_hi = [], []
    for crop in crops:
        res = fs["crops"][crop]
        colour = cfg.CROP_COLORS.get(crop, cfg.C_CURVE)
        ref = res["state"]["reference_yield_per_ha"]
        d = panel[panel["crop"] == crop]

        st = state_series(d)
        idx = 100.0 * st / ref
        xs = [x_index[s] for s in st.index]
        ys = idx.tolist()
        ax.plot(
            xs, ys, color=colour, lw=2, zorder=3,
            label=f"{cfg.CROP_LABELS.get(crop, crop)}   ·   skill {res['skill_rmse']:+.3f}",
        )
        scale_lo.extend(ys)

        # 2026: the dashed segment to the predicted state yield/area
        pred_index = 100.0 * res["state"]["yield_2026_per_ha"] / ref
        ax.plot(
            [xs[-1], x_index["2026"]], [ys[-1], pred_index], color=colour,
            lw=2, ls="--", zorder=3,
        )
        ax.scatter(
            [x_index["2026"]], [pred_index], s=64, marker="D", color=colour,
            edgecolor="white", linewidth=1.4, zorder=5,
        )
        scale_lo.append(pred_index)

    # the Telangana average, and the 2016 boundary
    ax.axhline(100, color="#b3ab9b", lw=1, ls=":", zorder=1)
    ax.text(
        -0.35, 100.6, "Telangana average = 100", fontsize=7.5,
        color="#8a8375", va="bottom",
    )
    ax.axvline(boundary, color="#b3ab9b", lw=1, ls=":", zorder=1)
    ax.text(
        boundary + 0.12, 0.02, "2016 reorganisation",
        transform=ax.get_xaxis_transform(), fontsize=7,
        color="#8a8375", va="bottom",
    )

    lo, hi = min(scale_lo), max(scale_lo)
    pad = (hi - lo) * 0.12 or 2
    ax.set_ylim(max(0, lo - pad), hi + pad)
    ax.set_xlim(-0.6, len(x_axis) - 0.4)
    ax.set_xticks(range(len(x_axis)))
    ax.set_xticklabels(x_axis, rotation=45, ha="right", fontsize=7.5)
    ax.set_ylabel(
        "state yield per hectare, indexed (Telangana average = 100)",
        fontsize=8.5,
    )
    style_axis(ax)

    handles, labels = ax.get_legend_handles_labels()
    legend = fig.legend(
        handles, labels, loc="lower center", ncol=4, frameon=False,
        fontsize=8, bbox_to_anchor=(0.5, 0.075),
    )
    for line in legend.get_lines():
        line.set_linestyle("-")

    txt = (
        "2026 is a model prediction, not an observation and not a validated forecast. Each crop "
        "is forecast by its own specification, selected by leave-one-season-out cross-validation "
        "inside the fitting period; the out-of-sample skill score against a district-median "
        "baseline is printed in the legend. The state line is area-weighted (sum of area x yield / sum "
        "of area) on the districts reporting in each season, indexed to the crop's own Telangana "
        "average over 2016-17 - 2022-23. Yield per hectare is the measure; the 2026 figures use "
        "2022-23 kharif area as the baseline, because a 2026 planted area does not exist. ERA5 is "
        "a 0.25 deg reanalysis, not station gauge data. No irrigation data is used."
    )
    fig.text(0.005, 0.012, txt, fontsize=6.4, color="#444444", va="bottom", wrap=True)
    fig.tight_layout(rect=(0, 0.125, 1, 1))
    out = cfg.FIGURES / "f6_forecast.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log(f"    wrote {out}")


def figure_f7(panel: pd.DataFrame, fs: dict) -> None:
    """The four panels, each in its own crop's unit."""
    log("  F7: the four per-crop panels")

    seasons = sorted(panel["season"].unique())
    x_axis = seasons + ["2026"]
    x_index = {s: i for i, s in enumerate(x_axis)}
    boundary = x_index[cfg.PRIMARY_PANEL_START] - 0.5

    crops = [c for c in cfg.TARGET_CROPS if c in fs["crops"]]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.6))

    for i, crop in enumerate(crops):
        ax = axes[i // 2][i % 2]
        res = fs["crops"][crop]
        colour = cfg.CROP_COLORS.get(crop, cfg.C_CURVE)
        unit = res["unit"]
        d = panel[panel["crop"] == crop]

        pre = d[d["era"] == "pre2016"]
        post = d[d["era"] == "post2016"]
        ax.scatter(
            pre["season"].map(x_index), pre["yield"], s=13, alpha=0.45,
            color="#9aa1ab", edgecolor="none", zorder=2,
            label="9 undivided parent districts",
        )
        ax.scatter(
            post["season"].map(x_index), post["yield"], s=13, alpha=0.45,
            color=colour, edgecolor="none", zorder=2,
            label="32 post-reorganisation districts",
        )

        st = state_series(d)
        xs = [x_index[s] for s in st.index]
        ys = st.tolist()
        ax.plot(xs, ys, color=colour, lw=2, zorder=3, label="state yield/area")

        state = res["state"]
        last_x = xs[-1]
        pred = state["yield_2026_per_ha"]
        ax.plot(
            [last_x, x_index["2026"]], [ys[-1], pred], color=colour, lw=2,
            ls="--", zorder=3, label="2026 prediction",
        )
        ax.scatter(
            [x_index["2026"]], [pred], s=70, marker="D", color=colour,
            edgecolor="white", linewidth=1.4, zorder=5,
            label="2026 predicted yield/area",
        )

        ax.axvline(boundary, color="#b3ab9b", lw=1, ls=":", zorder=1)
        ax.text(
            boundary + 0.12, 0.02, "2016 reorganisation",
            transform=ax.get_xaxis_transform(), fontsize=7,
            color="#8a8375", va="bottom",
        )

        scale = ys + [pred]
        lo, hi = min(scale), max(scale)
        pad = (hi - lo) * 0.18 or 0.1
        ax.set_ylim(max(0, lo - pad), hi + pad)
        ax.set_xlim(-0.6, len(x_axis) - 0.4)

        ax.set_xticks(range(len(x_axis)))
        ax.set_xticklabels(x_axis, rotation=45, ha="right", fontsize=7)
        ax.set_ylabel(f"yield/area ({unit})", fontsize=8.5)
        skill = res["skill_rmse"]
        ax.set_title(
            f"{cfg.CROP_LABELS.get(crop, crop)}   ·   skill {skill:+.3f}",
            loc="left", fontsize=10, color="#16181d",
        )
        style_axis(ax)

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", ncol=5, frameon=False,
        fontsize=8, bbox_to_anchor=(0.5, 0.005),
    )

    txt = (
        "2026 is a model prediction, not an observation and not a validated forecast. "
        "Each crop is forecast by its own specification, selected by leave-one-season-out "
        "cross-validation inside the fitting period; the out-of-sample skill score against a "
        "district-median baseline is printed on each panel. Yield per hectare is the measure; "
        "the state figures are area-weighted (sum of area x yield / sum of area) on 2022-23 "
        "kharif area, the baseline for a 2026 area that does not exist. ERA5 is a 0.25 deg "
        "reanalysis, not station gauge data. No irrigation data is used."
    )
    fig.text(0.005, 0.038, txt, fontsize=6.4, color="#444444", va="bottom", wrap=True)
    fig.tight_layout(rect=(0, 0.085, 1, 1))
    out = cfg.FIGURES / "f7_forecast_panels.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log(f"    wrote {out}")


def main() -> None:
    log("Step 17: figures F6 and F7 - the 2026 forecast")

    panel = pd.read_parquet(cfg.PROCESSED / f"panel_v{VERSION}.parquet")
    fs = cfg.read_json(cfg.PROCESSED / "forecast_series.json")

    figure_f6(panel, fs)
    figure_f7(panel, fs)


if __name__ == "__main__":
    main()
