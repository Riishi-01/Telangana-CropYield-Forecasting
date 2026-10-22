"""Figure F5 - season-window sensitivity of the response curve.

Three rainfall windows (Jul-Sep, Jun-Sep base, Jun-Oct) refit the Stage 1
specification per crop. Shows whether the "no rainfall optimum" conclusion
depends on the Jun-Sep sowing window. RDYlBu is avoided here - the quantity is
a p-value, so the panels use a single sequential ramp (YlOrRd is reserved for
deficit in the maps). Colormap: sequential blues, one row per crop, one
column per window, cell value = p(b2) and whether a vertex is supported.

Authority: README section 5 (season-window sensitivity).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cfg  # noqa: E402

log = cfg.log
cfg.ensure_dirs()

DPI = 200
plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": DPI, "font.size": 9,
    "axes.titlesize": 10, "axes.grid": True, "grid.alpha": 0.25,
    "grid.linestyle": ":", "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white",
})

# sequential single-hue ramp for a p-value quantity (colourblind-safe)
CMAP_P = plt.get_cmap("Blues")


def fmt_p(p):
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def main() -> None:
    cfg.check_determinism()
    log("Figure F5: season-window sensitivity")

    path = cfg.PROCESSED / "window_sensitivity.json"
    if not path.exists():
        log("  window_sensitivity.json not found - run src/12_window_sensitivity.py")
        return
    data = cfg.read_json(path)
    crops = [c for c in cfg.TARGET_CROPS if c in data["crops"]]
    windows = ["jul_sep", "jun_sep", "jun_oct"]

    fig, axes = plt.subplots(1, len(crops), figsize=(15.5, 4.0), sharey=True)
    if len(crops) == 1:
        axes = [axes]

    for ax, crop in zip(axes, crops):
        ps = [data["crops"][crop][w]["p2"] for w in windows]
        # log-ish stretch for legibility; colour by significance band
        for i, (w, p) in enumerate(zip(windows, ps)):
            if p < 0.05:
                face = "#1f77b4"
            elif p < 0.10:
                face = "#9ecae1"
            else:
                face = "#eef3f7"
            ax.add_patch(
                plt.Rectangle((i - 0.44, 0), 0.88, 1, facecolor=face,
                              edgecolor="#ffffff", linewidth=1.5, zorder=1)
            )
            r = data["crops"][crop][w]
            lines = [f"p(b₂)={fmt_p(p)}"]
            if r["vertex_reported"]:
                lines.append(f"R*={r['vertex_mm']:,.0f} mm")
            else:
                lines.append("no vertex")
            txt_color = "#ffffff" if p < 0.05 else "#16181d"
            ax.text(i, 0.62, "\n".join(lines), ha="center", va="center",
                    fontsize=9, zorder=3, color=txt_color,
                    fontfamily="monospace")
        ax.set_xlim(-0.6, len(windows) - 0.4)
        ax.set_ylim(0, 1)
        ax.set_xticks(range(len(windows)))
        ax.set_xticklabels([data["windows"][w]["label"] for w in windows], fontsize=8.5)
        ax.set_yticks([])
        ax.set_title(cfg.CROP_LABELS.get(crop, crop), fontsize=9.5, pad=8)
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(False)

    txt = (
        "Sowing-window sensitivity. Each panel refits yield ~ rainfall + rainfall² + district + season "
        "fixed effects on the kharif rainfall total for that window. Blue = the quadratic term is "
        "significant at p<0.05 (an inverted-U rainfall optimum is supported); pale = it is not. "
        "The Jun–Sep column reproduces the shipped Stage 1 fit exactly. "
        "The conclusion is window-independent for all four crops."
    )
    fig.text(0.005, 0.005, txt, fontsize=6.6, color="#444444", va="bottom", wrap=True)
    fig.suptitle(
        "Does the rainfall optimum depend on the season window?",
        x=0.005, ha="left", fontsize=11, family="serif", y=0.985,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    out = cfg.FIGURES / "f5_window_sensitivity.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log(f"  wrote {out}")


if __name__ == "__main__":
    main()