# Telangana kharif yield–weather explorer

**How much of a kharif season's outcome is explained by how much it rained?**

An empirical analysis of the relationship between kharif-season rainfall and crop yield
across Telangana's districts, with an interactive dashboard for exploring it. Yields come
from the Directorate of Economics & Statistics (DES); rainfall comes from ERA5 reanalysis
via the Open-Meteo archive API. Nothing here is a forecast.

- **DATA_VERSION** `1.1.0`
- **Scope** Telangana · Kharif · 2014-15 → 2022-23 · four crops (Cotton lint, Arhar/Tur, Moong, Rice)
- **Primary panel** 2016-17 → 2022-23, 32 post-reorganisation districts
- **Extended panel** 2014-15 → 2022-23, era-tagged district ids (robustness only)
- **Interactive explorer** `dashboard/index.html` — open it directly, no server needed

> **The headline result is a null result, and it is reported as one.** For the three
> rainfed primary crops — cotton, arhar/tur and moong — the quadratic rainfall term is
> **not statistically significant**, so no rainfall optimum (R\*) can be claimed. Only
> rice, the irrigation-buffered control, shows a significant inverted-U. Out of sample,
> the weather-only model **does not beat a district-crop median baseline** for three of
> the four modelled crops. See [Results](#4-results).

---

## 1. What this is

A reproducible pipeline that preprocesses the DES district-wise kharif statistics into a
clean 4-crop dataset, joins it to ERA5 rainfall features, estimates a fixed-effects
rainfall–yield response curve, tests whether dry-spell and heat-stress features add
anything beyond cumulative rainfall, checks whether the conclusion survives a different
season window, and validates the model out of sample against a median baseline. The
interactive dashboard is the readable face of the same numbers — it contains no value
that is not in `data/processed/`.

## 2. Data sources, licence and attribution

| Source | What it provides | Licence / attribution |
|---|---|---|
| **DES** district-wise season-wise crop production statistics (Directorate of Economics & Statistics, Govt. of India) | District × season × crop area, production, yield, 2014-15 → 2022-23 | Government open data, free for non-commercial use, attribution requested |
| **ERA5 reanalysis** via the [Open-Meteo archive API](https://open-meteo.com/en/docs/historical-weather-api) | Daily precipitation, temperature, VPD, radiation at the district centroids, 2014-06-01 → 2023-10-31 plus a 2026-06-01 → 2026-09-30 marker window | **CC BY 4.0 — attribution is mandatory** |
| **District boundaries** from [gpavanb1/Telangana-Visualisation](https://github.com/gpavanb1/Telangana-Visualisation) (`data/Telangana.geojson`) | 32 district polygons + Hyderabad | Open Government Data / community GeoJSON; source URL and SHA-256 recorded in `data/manifests/geo.json` |
| **Fonts** Instrument Serif, IBM Plex Sans, IBM Plex Mono | Dashboard typography | SIL Open Font License 1.1, self-hosted in `dashboard/assets/fonts` |

**ERA5 is a reanalysis, not a station observation.** The delivered DES file is an HTML
document despite its `.xls` extension and is parsed with `pandas.read_html()`.

## 3. The preprocessed dataset

`data/processed/crops_kharif_clean.csv` — the deliverable. **940 rows × 13 columns.**

| Column | Meaning |
|---|---|
| `season` | `2014-15` … `2022-23` |
| `season_year` | the year the kharif season opens (2014 = 2014-15) |
| `district`, `district_slug` | `Adilabad` / `adilabad` — the index prefix is stripped |
| `era` | `pre2016` (2014-15, 2015-16) or `post2016` (2016-17 onward) — the 2016 boundary break is a data field, not a convention |
| `crop` | `Cotton (lint)`, `Arhar/Tur`, `Moong (green gram)`, `Rice` |
| `area_ha`, `area_unit` | planted area, `ha` for every crop |
| `production`, `production_unit` | `bales` for cotton, `tonnes` for the rest |
| `yield`, `yield_reported`, `yield_unit` | `bales/ha` for cotton, `t/ha` for the rest |

**What was removed.** The source file is 238 district-seasons × 36 crop groups = 8,568
long rows in 111 columns. The 32 out-of-scope crop groups (7,628 rows and 96 columns)
are dropped, along with the constant `State` column, the redundant `Year` column, the
always-Kharif `session` column, and the 3-level MultiIndex header. A further **12 rows**
are removed by the quality rules (`area == 0`, `production == 0`, `area < 10 ha`, missing
value) — for these four crops the only rules that bite are *area below 10 ha* and
*missing values*: arhar `jayashankar 2022-23`; moong `jogulamba` ×4, `medchal` ×5,
`mulugu 2022-23`, `peddapalli 2021-22`. Every removed row and its reason is listed in
`data/processed/crops_kharif_clean.metadata.json`.

**Units are read from the source column labels and never converted.** Cotton is reported
in bales, the other three crops in tonnes, area is hectares throughout. No bale-to-tonne
factor is applied: that would be an assumption, not a cited value in this file, and
cotton is modelled on the bales scale. Cross-crop comparability comes from percentage
effects, never from a converted scale.

**Precision.** The DES publishes yield rounded to two decimals. `yield_reported` is that
value as published; `yield` is `production / area_ha` at full precision and is the
modelling target, because 2 dp is a coarse grid for moong — a 0.01 step on a median of
0.63 t/ha is 1.6 %, the same order as the effects being measured. A hard gate asserts
`yield == round(yield_reported, 2)` on every row; it passes on all 940.

## 4. Method

**Season window.** 1 June – 30 September, the official kharif sowing window (Telangana
District Collectorate). The ingest window is wider (1 June – 31 October) so late-season
dry spells and heat are captured in the spell and heat features.

**Weather features** (per district × season, `src/04_features.py`)

| Feature | Rule |
|---|---|
| `rain_mm` | Σ precipitation, 1 Jun – 30 Sep |
| `rain_days` | days with precipitation ≥ 2.5 mm (WMO standard rain-day definition) |
| `dry_run_max` | longest run of days with precipitation < 2.5 mm (Jun – Oct) |
| `dry_days_ge5` | days inside runs of ≥ 5 days (Jun – Oct) |
| `heat_days` | days with Tmax > 35 °C |
| `vpd_mean`, `tmax_mean` | means over the analysis window |

Every window closes before harvest; no feature looks past the end of its own window.

**Stage 1 — response curve (headline).** OLS:

```
yield ~ rain_mm + I(rain_mm²) + C(district_era) + C(season)
```

The rainfall optimum is `R* = −b₁ / (2·b₂)`, reported **only** when `b₂ < 0` and
`p(b₂) < 0.05`. Each crop is also refitted without season fixed effects, as a
linear-only model, and on the extended panel. All of those results are in
`data/processed/model_summary.json` and in the table below.

**Stage 2 — augmented model.** The same specification plus `dry_run_max`,
`dry_days_ge5`, `heat_days`, `vpd_mean`, `rain_days`. The reported quantity is
**ΔR² = R²(Stage 2) − R²(Stage 1)**, with the change in adjusted R² and a partial
F-test on the added block.

**Window sensitivity.** The same Stage 1 model is refitted on three rainfall windows —
Jul–Sep, Jun–Sep (base) and Jun–Oct — to test whether the conclusion depends on the
sowing window (`src/12_window_sensitivity.py`). A gate asserts the base window
reproduces the shipped Stage 1 fit exactly.

**Validation.** Chronological split only — train ≤ 2019-20 (4 seasons), test ≥ 2020-21
(3 seasons). Random splits leak across autocorrelated weather years, and none appear in
the codebase. The baseline is the district-crop median yield computed on the train
period only. Skill = 1 − RMSE_model / RMSE_baseline.

**Why the effective sample is smaller than the row count.** Rainfall is a
district-year variable; yield is a district-year-crop variable. For a single-crop
model the effective independent sample is the number of district-seasons, not the number
of rows times the number of crops.

**Districts and boundaries.** The DES file is the source of truth for district
membership. Districts are era-tagged (`{slug}__pre2016` / `{slug}__post2016`) so the
2016 reorganisation is an explicit break rather than a silent splice — see
§8 for what the reorganisation actually is.

**District coordinates.** Area-weighted centroid of the ERA5 0.25° grid cells that fall
inside each district polygon, for all 32 districts. The method and the boundary file's
SHA-256 are recorded in `data/manifests/geo.json`.

## 5. Results

Primary panel, 2016-17 → 2022-23, district + season fixed effects.
`b₁` is the linear rainfall term, `b₂` the quadratic term.

### Stage 1 — the rainfall response

| Crop | Unit | n | b₁ (per mm) | p | b₂ | p | R² | Rainfall optimum R\* |
|---|---|---|---|---|---|---|---|---|
| Cotton (lint) | bales/ha | 220 | +0.001466 | 0.118 | −4.35×10⁻⁷ | 0.293 | 0.570 | **not supported** — quadratic term n.s. |
| Arhar / Tur | t/ha | 219 | +0.004614 | 0.090 | −2.23×10⁻⁶ | 0.069 | 0.249 | **not supported** — quadratic term n.s. |
| Moong (green gram) | t/ha | 209 | −0.000005 | 0.986 | −4.53×10⁻⁸ | 0.714 | 0.545 | **not supported** — quadratic term n.s. |
| Rice | t/ha | 220 | +0.001474 | 0.005 | −5.44×10⁻⁷ | 0.018 | 0.732 | **1,354 mm** (95% CI 1,021 – 1,688) |

**Read this carefully.** For cotton, arhar and moong there is no statistically
supported inverted-U: the quadratic term is insignificant in the primary
specification, in the no-season-FE specification, and on the extended panel. The
data do not support a rainfall optimum for these crops, and this report does not
manufacture one. The figure and the dashboard say so in words.

For **rice** the quadratic term is significant, but the vertex needs two caveats.
It sits at the **95th percentile** of observed rainfall, and the fitted curve is
still rising over most of the observed range — the "optimum" is at the wet edge of
the data, not a local maximum within it. The no-season-FE specification gives **no**
vertex (p = 0.355), while the extended panel gives 1,350 mm. Per the guide's rule,
the year-FE specification is primary and the divergence is flagged.

A linear-only specification (no quadratic term) is significant for cotton
(b₁ = +0.000520, p = 0.042) and rice (b₁ = +0.000289, p = 0.043), and not for arhar
(p = 0.838) or moong (p = 0.152).

### Season-window sensitivity — the conclusion does not depend on the window

The Jun–Sep window is the *sowing* window, not the growing season, so the model is
refitted on two alternatives. p is the p-value of the quadratic term; a vertex is
reported only when the term is negative and significant at p < 0.05.

| Crop | Jul–Sep (92 d) | Jun–Sep (122 d, base) | Jun–Oct (153 d) |
|---|---|---|---|
| Cotton (lint) | p = 0.142 · no vertex | p = 0.293 · no vertex | p = 0.315 · no vertex |
| Arhar / Tur | p = 0.223 · no vertex | p = 0.069 · no vertex | p = 0.406 · no vertex |
| Moong (green gram) | p = 0.646 · no vertex | p = 0.714 · no vertex | p = 0.386 · no vertex |
| Rice | p = 0.001 · **R\* = 1,177 mm** | p = 0.018 · **R\* = 1,354 mm** | p = 0.006 · **R\* = 1,411 mm** |

**The conclusion is window-independent.** The same three crops support no inverted-U
under all three windows, and rice supports one under all three. Rice's vertex does move
with the window (1,177 → 1,354 → 1,411 mm), which is expected — the vertex is a
rainfall quantity, so it scales with the rainfall total it is measured against, and
comparing the three numbers directly is meaningless. What is comparable is the *shape* of
the finding, and that is stable. The Jun–Sep column reproduces the shipped Stage 1 fit
exactly, which is a gate in the build.

### Stage 2 — do dry spells and heat add anything?

| Crop | R² Stage 1 | R² Stage 2 | ΔR² | Δ adjusted R² | partial F p | Verdict |
|---|---|---|---|---|---|---|
| Cotton (lint) | 0.570 | 0.600 | **+0.030** | +0.023 | **0.024** | dry-spell/heat features **add** explanatory power beyond cumulative rainfall |
| Arhar / Tur | 0.249 | 0.269 | +0.020 | −0.001 | 0.448 | cumulative rainfall is sufficient; the increase is not robust |
| Moong (green gram) | 0.545 | 0.558 | +0.013 | −0.001 | 0.460 | cumulative rainfall is sufficient; the increase is not robust |
| Rice | 0.732 | 0.739 | +0.007 | −0.001 | 0.487 | cumulative rainfall is sufficient; the increase is not robust |

This is the test of Bal et al. (2022)'s central claim on open data for Telangana, and
the answer is **crop-specific**. For cotton the dry-spell and heat block adds
explanatory power that is detectable on both Δ adjusted R² and the partial F-test. For
arhar, moong and rice the raw ΔR² is positive but the change disappears once the five
extra parameters are accounted for. One partial confirmation is not a general result,
and the full numbers are reported for every crop.

One further detail: the Stage 2 arhar model *does* carry a significant quadratic term
(p = 0.026, R\* = 1,083 mm) once the dry-spell and heat terms are in the model, which
Stage 1 does not. That is a specification-dependent result and is reported as such.

### Validation — does the model beat a median baseline?

Chronological split: train 2016-17 … 2019-20, test 2020-21 … 2022-23. Baseline is the
district-crop median yield computed on the train period only.

| Crop | RMSE model | RMSE baseline | Skill | Skill, no season FE |
|---|---|---|---|---|
| Cotton (lint) | 0.788 | 0.561 | **−0.405** | −0.354 |
| Arhar / Tur | 1.885 | 1.949 | **+0.033** | +0.031 |
| Moong (green gram) | 0.261 | 0.255 | **−0.023** | −0.035 |
| Rice | 0.502 | 0.452 | **−0.111** | −0.010 |

**Weather alone does not predict district-level kharif yield.** For cotton, moong and
rice the model is *worse* than simply reporting the district's own ten-year median; only
arhar shows a positive skill, and it is +0.03 — a 3 % RMSE reduction, which is not a
practical forecasting tool.

One caveat on the evaluation, stated plainly: the primary specification differences out
the common year effect, and the test seasons' year effects are not estimable from the
training data. Test rows are therefore predicted with the reference season's effect.
The no-season-FE column re-runs the test without differencing out the year and gives
the same answer for every crop, so the conclusion does not rest on that convention.

### The 2026 rainfall reading

ERA5 observed kharif rainfall for 1 Jun – 30 Sep 2026, across the 32 district
centroids: **state mean 488 mm**, median 439 mm, p10–p90 = 285–731 mm, range 248–816 mm.
The fitting period's observed range was 374–1,827 mm, so 2026 sits at the **1.4th
percentile** of the historical distribution and **9 of 32 districts fall below the
observed minimum**.

The dashboard and F1 therefore draw the 2026 rainfall as a dashed marker on the fitted
curve, with its district band, and state that any implied yield is a reading of the
curve and an extrapolation below the fitted range — not a forecast.

## 6. Figures

| File | What it shows |
|---|---|
| `figures/f1_response_curve.png` | Response curve per crop, Stage 1 beside Stage 2, vertex annotated where supported, 2026 rainfall marker |
| `figures/f2_timeseries.png` | Kharif rainfall and cotton yield by season, p10–p90 bands, stacked on a shared x-axis (no dual axis) |
| `figures/f3_validation.png` | Out-of-sample RMSE against the median baseline, and the skill score |
| `figures/f4_choropleth.png` | Cotton yield anomaly (%) by district for 2022-23, RdYlBu with zero at the midpoint |
| `figures/f5_window_sensitivity.png` | The response curve refitted on three season windows |

The interactive explorer is `dashboard/index.html`. It opens straight from disk
(`file://`), needs no server, and fetches nothing from a CDN: Plotly, Leaflet and the
fonts are vendored in the repository. The map offers three metrics — yield anomaly
(RdYlBu, the default), absolute yield (Blues), and **rainfall deficit** (YlOrRd: this
season's rainfall against that district's own 2016-17–2022-23 median, so the map shows
where a season was dry *for that district* rather than for the state).

## 7. Limitations — all twelve

1. **Reanalysis, not observation.** ERA5 is a model-assimilated reanalysis product at
   0.25° (~25 km) resolution. It is not IMD station gauge data.
2. **Convective rainfall bias.** ERA5 is known to underestimate convective rainfall over
   dryland interiors. Absolute rainfall totals in this analysis may be biased low.
3. **No irrigation, soil, or input data.** This is the dominant confound. Reported
   effects are rainfall's marginal association **conditional on all other factors being
   average**, not a causal yield model.
4. **District aggregates, not farm-level.**
5. **Boundary discontinuity.** District boundaries were revised in 2016 and 2018.
   Pre- and post-revision periods are modelled as distinct fixed-effect groups, **not**
   as a continuous panel.
6. **Sowing window ≠ season.** Jun–Sep is the official kharif sowing window; cotton and
   arhar grow to Nov–Dec, so late-season rainfall is undercounted. (Tested: the
   conclusion does not change under Jul–Sep or Jun–Oct — see §5.)
7. **DES agency discontinuity.** Pre-2014 figures originate with undivided Andhra Pradesh
   DES; post-2014 with Telangana DES. Estimation methodology may differ.
8. **Cotton is reported in bales**, not tonnes, and is modelled on that scale.
9. **Small sample per crop.** ~220 district-year observations per crop in the primary
   panel.
10. **2026 is not forecast.** Response curve fitted on observed yields. 2026 rainfall is
    ERA5 observed. Any implied yield is a reading of the fitted curve, not a validated
    forecast — the extrapolation gap is 3+ years.
11. **Attribution.** ERA5 via Open-Meteo — CC BY 4.0. DES — Govt. of India open data.
12. **Rule-based percentile bands** are descriptive, not inferential. No confidence
    intervals are claimed.

Beyond the twelve, and specific to this build:

13. **The delivered DES file covers 2014-15 → 2022-23 only.** The specification assumed
    2000-01 → 2022-23; the file does not contain the earlier seasons. See
    `plan/ERRATA.md` — the file wins, and the panel windows were narrowed accordingly.
14. **No parent-district reconstruction is attempted.** The 2016 division is zero-sum
    (x → y+z ⟹ x = y+z), but Suryapet was formed from parts of two parents, so those
    parents cannot be rebuilt from the children the dataset names. Post-2016 districts
    are used as individual entities with their new names (`data/geo/PARTITION_NOTE.md`).
15. **The season fixed effects of the test period are unobserved.** Out-of-sample
    predictions use the reference season's effect; the no-season-FE column shows the
    conclusion is unchanged.
16. **Four crops only.** The source file carries 36 kharif crop groups; the other 32 are
    outside the project's scope and are not in the delivered dataset.

## 8. Reproduction

```bash
# 1. environment (Python 3.11+; 3.13 used here)
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python \
    pandas numpy pyarrow scipy statsmodels scikit-learn matplotlib requests jinja2 lxml

# 2. the pipeline, in order. Every step is deterministic.
export PYTHONHASHSEED=0
for step in 01_ingest_des 02_build_geo 03_fetch_era5 04_features \
            05_build_panel 06_model_stage1 07_model_stage2 08_validate \
            09_figures 12_window_sensitivity 12_figure_window \
            10_build_dashboard; do
    .venv/bin/python "src/${step}.py"
done

# 3. the checks
.venv/bin/python tests/verify_readme_numbers.py   # README vs the artefacts
bash tests/run_dashboard_qa.sh                     # 29 headless checks
```

- `src/03_fetch_era5.py` takes an optional window argument: `analysis` (default),
  `marker2026`, or `all`. The archive API enforces an hourly request quota; the
  fetcher retries with a 5 s pause on SSL/network drops, a 60 s cooldown on a generic
  429, and waits for the top of the next hour on the hourly-quota error. Raw
  responses are cached under `data/raw/openmeteo/` and are never re-fetched once
  present.
- `src/05_build_panel.py` re-verifies that the panel rebuilds byte-identically
  (SHA-256) and fails if it does not.
- `src/12_window_sensitivity.py` fails if the base window does not reproduce the
  shipped Stage 1 fit.
- The panel, the model summary and every manifest carry their own SHA-256 in
  `data/manifests/`.
- **What does and does not reproduce.** The data artefacts rebuild byte-identically
  (`panel_v1.1.0.parquet`, `crops_kharif_clean.csv`). The manifests and the dashboard
  bundle re-stamp their `created_utc` field on every run, so a rebuild leaves those
  seven files modified in git — that is by design, since the SRS requires every fetch
  to record its UTC timestamp. Nothing else differs.

**Environment note:** `data/raw/`, `data/interim/` and `data/processed/` are
gitignored — reproducibility is carried by the manifests and checksums, not by
committing blobs. The DES input file itself is copied to `data/raw/des/` and
checksummed there.

## 9. Coordinate source and the 2016 reorganisation

- **Boundaries:** `data/raw/geo/telangana_districts.geojson`, fetched from
  `https://raw.githubusercontent.com/gpavanb1/Telangana-Visualisation/master/data/Telangana.geojson`,
  SHA-256 `e228271e9929f716…`, recorded in `data/manifests/geo.json`. 33 features, 32
  used; Hyderabad is carried as an explicit no-data district because it has no yield
  observation in the delivered file.
- **Name crosswalk:** `data/geo/name_crosswalk.csv` — 13 DES names differ from the
  boundary file's spelling (e.g. `Jangoan` → `Jangaon`, `Mahbubnagar` →
  `Mahabubnagar`); all 32 districts join.
- **Coordinates:** area-weighted centroid of the intersecting ERA5 0.25° grid cells, for
  all 32 districts (`data/geo/districts.csv`).
- **The 2016 reorganisation is zero-sum.** When an undivided district *x* was divided
  into *y* and *z* in 2016, *x = y + z* — the land does not leave the parent. The
  children take the parent's name or a new one (Ranga Reddy → Rangareddy; Warangal →
  Warangal Rural + Warangal Urban), and the dataset reports them individually from
  2016-17 onward. A parent-level figure for a post-2016 season would be
  `sum(production_children) / sum(area_children)`. **That reconstruction is not
  attempted**: Suryapet was formed from parts of two parents (Khammam and Nalgonda),
  so those parents cannot be rebuilt from the children the dataset names, and it is
  unnecessary — era-tagged fixed effects keep pre- and post-2016 districts apart, so
  no undivided district is ever compared to a post-2016 one as if it were the same
  unit. An area-based check of the zero-sum property was inconclusive (residuals
  +65 % to −70 %, swamped by crop choice), so the zero-sum status is a fact of the
  reorganisation, not a measurement. Full reasoning: `data/geo/PARTITION_NOTE.md`.

## 10. Repository map

```
data/raw/          immutable source responses (gitignored, checksummed)
data/interim/      long-format DES, daily weather, features (gitignored)
data/processed/    crops_kharif_clean, panel, model summary (gitignored)
data/geo/          districts.csv, districts.geojson, name_crosswalk.csv, PARTITION_NOTE.md
data/manifests/    fetch_manifest.json, checksums.sha256, per-stage manifests
src/01..12         the pipeline, one script per stage
figures/           F1–F5 static PNGs
dashboard/         the static interactive site
tests/             artefact verification and the headless dashboard QA
plan/              SRS.md, GUIDE.md, ERRATA.md
```

**Git policy:** local commits only. No remote is configured, and no push has been
performed — the owner controls all remotes, releases and tags.
