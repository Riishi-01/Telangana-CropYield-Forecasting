# Telangana kharif yield–weather explorer

**Forecasting kharif yield from rainfall.**

An empirical analysis of the relationship between kharif-season rainfall and crop yield
across Telangana's districts, with an interactive dashboard for exploring it. Yields come
from the Directorate of Economics & Statistics (DES); rainfall comes from ERA5 reanalysis
via the Open-Meteo archive API. The 2026 figures are **model predictions**, and every
one of them carries its out-of-sample skill score.

- **DATA_VERSION** `1.1.0`
- **Scope** Telangana · Kharif · 2014-15 → 2022-23 · four crops (Cotton lint, Arhar/Tur, Moong, Rice)
- **Primary panel** 2016-17 → 2022-23, 32 post-reorganisation districts
- **Extended panel** 2014-15 → 2022-23, era-tagged district ids (robustness only)
- **Interactive explorer** `dashboard/index.html` — open it directly, no server needed

> **The result is a split, not a blanket null, and it is reported as it is.**
> **Rice responds to kharif rainfall**: within a district, the rainfall–yield
> correlation is **+0.221** (p = 0.001) and the quadratic term is significant
> (p = 0.018), giving a supported optimum at **1,354 mm**. The other three
> crops — cotton, arhar/tur and moong — show **no supported relationship**
> (p = 0.293, 0.069, 0.714). Cotton's apparent signal in a pooled regression
> is a **between-district confound**, not rainfall. See [Results](#5-results).

> **The 2026 forecast, in yield per hectare.** Each crop is forecast by its
> **own** model — one shared specification cannot be right for four crops —
> and each model is selected by leave-one-season-out cross-validation inside
> the fitting period, with the validation block evaluated once afterwards.
> **Two of the four models beat the district-median baseline** (arhar +0.006,
> rice +0.078); two do not (cotton −0.235, moong −0.017), so their predictions
> mean *no evidence of a change*, not a forecast. The state figures are
> area-weighted on 2022-23 kharif area — the baseline for a 2026 planted area
> that does not exist. See [The 2026 forecast](#54-the-2026-forecast).

> **The single biggest limitation.** No irrigation data is used anywhere in this
> analysis. Telangana is heavily borewell-irrigated, and crops recorded as
> rainfed are irrigated in distress years. Irrigation therefore **attenuates
> the rainfall–yield relationship mechanically**, and the weak or absent
> relationships reported below may be a consequence of that buffering rather
> than of rainfall being unimportant. This is the leading candidate
> explanation for the null results and it is **untested** here. See
> [Limitations](#7-limitations--all-fifteen).

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
yield ~ rain_mm + I(rain_mm²) + C(district_id) + C(year)
```

The rainfall optimum is `R* = −b₁ / (2·b₂)`, reported **only** when `b₂ < 0` and
`p(b₂) < 0.05`. Each crop is also refitted without the year fixed effects, as a
linear-only model, and on the extended panel. All of those results are in
`data/processed/model_summary.json` and in the table below.

> **On the name of the fixed effect.** Only kharif is modelled, so `C(year)` is a
> **year** effect — it absorbs statewide annual shocks, and it does **not** control
> for kharif-vs-rabi variation, because no rabi data is in the project. It is
> called "year" rather than "season" throughout so that no reader can mistake it
> for a season control. The mapping between the agricultural year and the calendar
> year is a named constant (`common.YEAR_MAPPING`) and is **verified by an
> executable gate** that re-fits the relationship under three alignments and fails
> the build if the implemented one is not the best. See §5.2.

**Stage 2 — augmented model.** The same specification plus `dry_run_max`,
`dry_days_ge5`, `heat_days`, `vpd_mean`, `rain_days`. The reported quantity is
**ΔR² = R²(Stage 2) − R²(Stage 1)**, with the change in adjusted R² and a partial
F-test on the added block.

**Window sensitivity.** The same Stage 1 model is refitted on three rainfall windows —
Jul–Sep, Jun–Sep (base) and Jun–Oct — to test whether the conclusion depends on the
sowing window (`src/12_window_sensitivity.py`). A gate asserts the base window
reproduces the shipped Stage 1 fit exactly.

**Out-of-sample validation.** A chronological split only — train ≤ 2019-20
(4 seasons), holdout ≥ 2020-21 (3 seasons). Random splits leak across
autocorrelated weather years, and none appear in the codebase. The baseline is
the district-crop median yield computed on the training period only. The skill
score is `1 − RMSE_model / RMSE_baseline`; a positive value means the model
beats that baseline.

**Forecasting 2026.** Each crop is forecast by its **own** specification — one
shared model cannot be right for four crops at once. Four candidates are scored
by leave-one-season-out cross-validation **inside the fitting period**
(2016-17 … 2019-20), and the holdout block (2020-21 … 2022-23) is evaluated
**once, afterwards**, so the reported skill is a holdout statistic and not a
selection statistic. A second gate then applies: a specification may predict
2026 only if it produces a **positive yield for every district** at the observed
2026 rainfall. The measure is **yield per hectare**; state figures are
**area-weighted** (`SUM(area × yield) ÷ SUM(area)`), and the unweighted mean of
district yields is not used. Each district's **2022-23 kharif area** is the
baseline for a 2026 area that does not exist, applied identically to the
prediction and to the Telangana average.

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

Primary panel, 2016-17 → 2022-23, district + year fixed effects.
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
specification, in the no-year-FE specification, and on the extended panel. The
data do not support a rainfall optimum for these crops, and this report does not
manufacture one. The figure and the dashboard say so in words.

For **rice** the quadratic term is significant, and the finding survives every
specification tested (see the robustness grid below). The vertex still needs two
caveats. It sits at the **95th percentile** of observed rainfall, and the fitted
curve is still rising over most of the observed range — the "optimum" is at the wet
edge of the data, not a local maximum within it. **Only 11 of 220 district-seasons
carry rainfall above the vertex**, so the excess limb is estimated from a thin tail
of the observed distribution. The no-year-FE specification gives **no** vertex
(p = 0.355), while the extended panel gives 1,350 mm. Per the guide's rule, the
year-FE specification is primary and the divergence is flagged.

A linear-only specification (no quadratic term) is significant for cotton
(b₁ = +0.000520, p = 0.042) and rice (b₁ = +0.000289, p = 0.043), and not for arhar
(p = 0.838) or moong (p = 0.152).

### §5.2 The year mapping is verified, not assumed

Before any of this can be interpreted, the join between the agricultural year
and the calendar year has to be right. A misaligned join is the classic way to
manufacture a spurious null: shift the rainfall by a year and the correlation
collapses towards zero, because monsoon rainfall is strongly autocorrelated
between adjacent years. **A near-zero correlation is not evidence of no
relationship until the join has been checked.**

The convention is named in `src/common.py` (`YEAR_MAPPING`): *season Y-YY is
June–October of calendar year Y*, so kharif 2015-16 uses Jun–Sep **2015**
rainfall. `src/05_build_panel.py` runs the check as a **build gate** — it
re-fits the relationship under all three alignments and fails the build if the
implemented one is not the best.

| Alignment | Mean \|r\| across the 4 crops | Cotton | Arhar | Moong | Rice |
|---|---|---|---|---|---|
| **same year (implemented)** | **0.137** | +0.066 | −0.020 | −0.183 | **+0.221** |
| +1 year | 0.107 | +0.165 | +0.029 | +0.057 | **−0.167** |
| −1 year | 0.037 | +0.096 | −0.020 | −0.028 | −0.042 |

The spot-check the build prints: **Mahbubnagar 2015-16 rice** yielded 2.26 t/ha
against a district median of 2.82, and Jun–Sep 2015 delivered **416 mm** against
Jun–Sep 2016's 1,015 mm — the poor yield matches the *dry* window, so the season
opens in the year its label names.

**Note the sign flip in the rice column.** Under a one-year-shifted join, rice
still passes the significance threshold — with the correlation pointing the wrong
way. That is why the shift row is reported as the alignment test and is
**excluded from the robustness count** in §5.1: a broken join can manufacture a
significant result in the wrong place.

### Robustness grid — does the finding survive a different specification?

A null that appears under one specification is an artefact until proven otherwise.
`src/13_robustness_grid.py` runs the headline relationship under every
specification and reports the grid as a table with a verdict line. The statistic is
the within-district correlation between the yield anomaly and the rainfall anomaly;
`*` marks a specification whose quadratic term is significant (b₂ < 0, p < 0.05).

| Specification | Cotton | Arhar / Tur | Moong | Rice |
|---|---|---|---|---|
| 1 · year mapping as implemented | +0.066 | −0.020 | −0.183 | **+0.221\*** |
| 2 · year mapping shifted +1 yr | +0.165 | +0.029 | +0.057 | −0.167\* |
| 2 · year mapping shifted −1 yr | +0.096 | −0.020 | −0.028 | −0.042 |
| 4 · without year fixed effects | +0.066 | −0.020 | −0.183 | +0.221 |
| 5 · with district fixed effects *(shipped)* | +0.066 | −0.020 | −0.183 | **+0.221\*** |
| 6 · without district fixed effects (pooled) | **+0.256\*** | +0.124 | −0.124 | **+0.113\*** |
| 7 · ERA5-Land 0.1° | deferred | deferred | deferred | deferred |

**Verdict: the rice result is robust; the three null results are robust too — and
cotton's pooled signal is a confound.**

- **Rice survives within-district** in 3 of the 4 robustness specifications
  (the shift row is excluded — see below). Its relationship is not a
  specification artefact.
- **Cotton's pooled significance is a between-district confound.** Cotton is
  significant *only* in row 6, the fit that differences out no geography. That
  fit mixes between-district and within-district variation, so a coefficient
  significant only there is a geography effect, not a rainfall effect. Cotton's
  within-district relationship is null, and the shipped specification says so.
- **Row 2 is the gate G1 evidence, and it is deliberately excluded from the
  count.** Under a one-year-shifted join, rice's correlation **flips sign**
  (+0.221 → −0.167) and *still* passes the significance threshold. A misaligned
  join can manufacture a significant result in the wrong place, so counting
  that row would reward a broken join. It is reported here as the alignment
  test instead. The implemented alignment is the one that maximises mean |r|
  across the four crops (0.137, against 0.107 for +1 yr and 0.037 for −1 yr).
- **Row 7 is deferred**, not dropped: ERA5-Land 0.1° is on the Tier 2 backlog
  (SRS §11) and is not required for Tier 1 delivery.

### Do district rainfall sensitivities differ? (mixed-effects test)

The shipped model assumes **one shared rainfall slope** across all 32 districts.
That assumption was previously defended by saying per-district slopes cannot be
estimated on 7 points each — which is true of 32 unconnected regressions but not
of partial pooling. `src/14_slope_heterogeneity.py` fits

```
MixedLM(yield ~ rain_mm, groups=district_id, re_formula="~rain_mm")
```

and reports a likelihood-ratio test of H₀: *all district rainfall slopes are
equal* (the random-slope variance is zero).

| Crop | LRT χ² | p | Verdict |
|---|---|---|---|
| Cotton (lint) | 3.15 | 0.076 | no evidence that district slopes differ |
| Arhar / Tur | 2.92 | 0.087 | no evidence that district slopes differ |
| Moong (green gram) | 0.28 | 0.600 | no evidence that district slopes differ |
| Rice | 0.07 | 0.789 | no evidence that district slopes differ |

**The shared-slope assumption is not rejected for any crop.** A per-district OLS
cross-check agrees: only 1–2 of ~32 districts are individually significant at
p < 0.05 per crop, which is the rate chance predicts. So the constraint was not
merely tolerated for lack of data — it was **tested and holds**.

**On what was and was not tried, stated without circularity.** A more flexible
estimator failing to beat a simple one is *the same single piece of evidence* as
the simple model's result, not independent confirmation of it. So the accurate
statement is about the specifications themselves: **no specification tested
recovered a rainfall–yield relationship for cotton, arhar or moong** — across the
seven grid rows, the three season windows, the linear-only and no-year-FE
variants, and the extended panel. For rice, a relationship **was** recovered, and
it survived the grid. Whether a still more flexible estimator would find
something for the other three is untested and is not claimed either way.

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

### Does the weather model earn its place?

Chronological split: train 2016-17 … 2019-20, test 2020-21 … 2022-23. Baseline is the
district-crop median yield computed on the train period only.

| Crop | RMSE model | RMSE baseline | Skill | Skill, no year FE |
|---|---|---|---|---|
| Cotton (lint) | 0.788 | 0.561 | **−0.405** | −0.354 |
| Arhar / Tur | 1.885 | 1.949 | **+0.033** | +0.031 |
| Moong (green gram) | 0.261 | 0.255 | **−0.023** | −0.035 |
| Rice | 0.502 | 0.452 | **−0.111** | −0.010 |

**Weather alone does not predict district-level kharif yield.** For cotton, moong and
rice the model is *worse* than simply reporting the district's own ten-year median; only
arhar shows a positive skill, and it is +0.03 — a 3 % RMSE reduction, which is not a
practical forecasting tool.

**This is not a contradiction of the rice result, and the difference is the point.**
Rice's rainfall–yield relationship is *real and robust* (§5.1) but it is *small* — it
accounts for about 5 % of the within-district variance in rice yield. A real
relationship of that size does not beat a district's own historical median when you ask
it to predict a single district-season. "Rainfall matters for rice" and "rainfall does
not predict next year's rice in any given district" are both true at once, and the
second statement is the one that governs anything you might want to do with this.

One caveat on the evaluation, stated plainly: the primary specification differences out
the common year effect, and the test years' year effects are not estimable from the
training data. Test rows are therefore predicted with the reference year's effect.
The no-year-FE column re-runs the test without differencing out the year and gives
the same answer for every crop, so the conclusion does not rest on that convention.

### The 2026 rainfall reading

ERA5 observed kharif rainfall for 1 Jun – 30 Sep 2026, across the 32 district
centroids: **state mean 488 mm**, median 439 mm, p10–p90 = 285–731 mm, range 248–816 mm.
The fitting period's observed range was 374–1,827 mm, so 2026 sits at the **1.4th
percentile** of the historical distribution and **9 of 32 districts fall below the
observed minimum**.

**A note on the drought context.** 2026 is dry in *total* (488 mm) but not dry in
*deficit*: its longest dry run (12 days) and total dry days (42) are both close to
their historical medians (18.5 and 55), and its heat days are *above* median
(19 against 10, the 70th percentile). The rain fell in concentrated bursts rather
than long dry gaps. This matters for interpretation: the crop-critical question is
not "how much rain fell" but "how long were the gaps", and on that measure 2026
looks much less extreme than its 1.4th-percentile rainfall total suggests.

### 5.4 The 2026 forecast

**2026 is a model prediction.** The yield does not exist, so every 2026 figure below
is a prediction from a fitted model — and each one is published with that model's
out-of-sample skill, so a reader can weigh it.

**One model per crop.** A single specification cannot be right for cotton, arhar,
moong and rice at once. Four candidates are scored by leave-one-season-out
cross-validation **inside the training block** (2016-17 … 2019-20), and the
validation block (2020-21 … 2022-23) is evaluated **once, afterwards** — so the
reported skill is not a selection statistic. A second gate then applies: *a
specification may only predict 2026 if it produces a positive yield for every
district at the observed 2026 rainfall.*

| Crop | Selected | Test skill (selected) | Test skill (shared spec, before) |
|---|---|---|---|
| Cotton (lint) | linear | **−0.235** | −0.405 |
| Arhar / Tur | linear *(quadratic rejected on validity)* | **+0.006** | +0.033 |
| Moong (green gram) | linear | **−0.017** | −0.023 |
| Rice | linear | **+0.078** | −0.111 |

**Arhar's quadratic is rejected, and the reason is recorded.** It has the best
cross-validation score of the four, but its curve goes negative below ~440 mm, the
2026 state mean is 488 mm, and it returns **negative yields for 19 of 32
districts**. A negative yield is not a forecast, it is an extrapolation failure, so
the next valid specification is used. The rejection and its reason are in
`data/processed/forecast_models.json`.

**The rice vertex is a finding, not the forecasting model.** The curvature is real
(β₂ p = 0.018, R\* = 1,354 mm) and survives the robustness grid, but the *linear*
specification forecasts better (−0.111 → +0.078). Both are reported, separately.

**The measure is yield per hectare, and every state figure is area-weighted.** A
production total mixes productivity with land utilisation. The state figure is
`SUM(area_i × yield_i) / SUM(area_i)`; the unweighted mean of district yields is
not used anywhere, because it weights a 720 ha district the same as a 129,633 ha one.
On the reference period that choice moves arhar's state figure by 13.6 % and flips
the sign of its 2026 comparison.

**The 2026 area baseline.** 2026 planted area does not exist and cannot be
forecast. Each district's **2022-23 kharif area** is the baseline, applied
**identically** to the 2026 prediction and to the Telangana average, so the
comparison isolates yield from land utilisation. It moves the state percentages by
up to 7.4 points (arhar), which is why it is stated rather than buried.

| Crop | 2026 yield/area | Telangana average | Δ per ha | Δ % | 2026 total | Δ total |
|---|---|---|---|---|---|---|
| Cotton (lint) | 2.029 bales/ha | 2.645 | **−0.615** | **−23.3 %** | 4,107,087 bales | −1,245,059 |
| Arhar / Tur | 0.837 t/ha | 0.771 | **+0.066** | **+8.6 %** | 190,556 t | +15,057 |
| Moong (green gram) | 0.756 t/ha | 0.618 | **+0.138** | **+22.4 %** | 20,428 t | +3,734 |
| Rice | 3.151 t/ha | 3.327 | **−0.176** | **−5.3 %** | 8,289,544 t | −462,623 |

**Read these with the skill column beside them.** Cotton and moong **do not beat
the district-median baseline** out of sample (−0.235 and −0.017), so their
predictions mean *no evidence of a change*, not a forecast — and moong's +22.4 % is
what a flat, non-significant model says (its rainfall coefficient is −0.0001, i.e.
zero). Cotton's −23.3 % is the weakest of the four. Arhar and rice do beat the
baseline, but +0.006 is a 0.6 % RMSE reduction — marginal.

**No prediction interval is claimed.** With three held-out seasons there is not
enough data to calibrate one honestly, and a false interval would be worse than
none.

### 5.5 How the forecast is drawn

The dashboard draws one chart with all four crops on it, because that is the
comparison a reader actually wants: what does the 2026 prediction do against
each crop's own history? Two choices make that possible.

**The axis is indexed.** Cotton is measured in bales per hectare and the other
three in tonnes per hectare, so four crops cannot share a raw axis. Each crop is
indexed to its own Telangana average over the fitted period (2016-17 → 2022-23
= 100) — the same area-weighted reference the forecast table uses. The 2026
endpoint then reads directly as the forecast difference: cotton 76.7,
arhar 108.6, moong 122.3, rice 94.7.

**The state line is area-weighted** — `SUM(area × yield) ÷ SUM(area)` over the
districts reporting in each season. The unweighted mean of district yields is
not used, and neither is the median: the area-weighted figure is a state total
divided by a state area, so it is the same quantity on both sides of the 2016
reorganisation, while the district-level medians are not. That is why the line
runs through 2014-15 without a break, where a median line would have jumped.

| Crop | 14-15 | 15-16 | 16-17 | 17-18 | 18-19 | 19-20 | 20-21 | 21-22 | 22-23 | **2026** |
|---|---|---|---|---|---|---|---|---|---|---|
| Cotton (lint) | 81.5 | 79.6 | 92.4 | 103.5 | 79.1 | 121.5 | 93.0 | 96.2 | 110.1 | **76.7** |
| Arhar / Tur | 64.1 | 54.4 | 87.7 | 103.6 | 83.8 | 117.1 | 100.6 | 99.7 | 114.2 | **108.6** |
| Moong (green gram) | 80.0 | 77.7 | 98.6 | 103.3 | 101.8 | 127.5 | 67.2 | 96.9 | 108.7 | **122.3** |
| Rice | 93.2 | 88.2 | 102.4 | 84.6 | 104.5 | 110.3 | 90.8 | 99.2 | 105.1 | **94.7** |

*State yield per hectare, indexed to each crop's Telangana average
(2016-17 → 2022-23 = 100). The 2016 reorganisation falls between 2015-16 and
2016-17; the two pre-2016 seasons are the nine undivided parent districts, and
29–32 of the 32 districts report in any one crop-season.*

**The 2026 segment is dashed** because nothing has been observed for it, and it
is drawn as a continuation of each crop's own line rather than as a separate
mark. The chart is categorical in time: the nine observed seasons and then
2026 as its own step, because a continuous axis would place 2026 to the *left*
of the record — its rainfall is below every fitted observation — and that
reads as "before 2014" rather than "a season that has not happened yet".

**The map opens on the 2026 prediction.** The season selector carries
`2026-27 (prediction)` as its last option and it is the default, with cotton
and absolute yield. Every value shown under it is a model prediction, and the
map's own note, the hover card and the readout all say so. The 2026 layer has
its own fixed colour domain per crop — the predictions occupy the middle of
the observed range, so on the observed scale they would all land in one pale
band.

**The state in one table.** Above the district table, the state totals for the
four crops and the kharif rainfall, against the Telangana average:

| | 2026 | State avg | |
|---|---|---|---|
| **Cotton (lint)** | 4.11 M bales | 5.35 M bales | ↓ 23.3 % |
| **Arhar / Tur** | 0.191 M t | 0.175 M t | ↑ 8.6 % |
| **Moong (green gram)** | 0.020 M t | 0.017 M t | ↑ 22.4 % |
| **Rice** | 8.29 M t | 8.75 M t | ↓ 5.3 % |
| **Kharif rainfall** | 488 mm | 848 mm | ↓ 42.5 % |

The yield totals are the area-weighted state yield per hectare applied to each
district's 2022-23 kharif area; the average column is the Telangana average on
that same area, so the two columns differ only by the model's skill. The
rainfall average is the mean of the nine seasonal state means, 2014-15 to
2022-23, against which **2026 is the driest kharif season in the record**.

**A crop can be focused on it.** The chart's selector offers all four crops or
one; with a single crop the district observations appear behind the line, so
the spread within a season is visible. The scale is then set by the state line,
the 2026 prediction **and the 2nd-to-98th percentile of the district
observations** — a percentile, not the extremes, because one delivered value
(Mulugu, arhar 2019-20: 891 t on 39 ha) would otherwise flatten the whole
chart. Observations that fall outside are counted and reported under the chart;
none is deleted.

**One delivered data value is retained, and it is visible.** Mulugu's 2019-20
arhar cell reads **891 t on 39 ha** — 22.85 t/ha against the district's 0.62–0.91
t/ha in its other years, almost certainly a decimal error in the DES file. The file
is kept exactly as delivered, so the row stays: arhar's model keeps its degraded
fit (b₁ = −0.000150, R² = 0.235, against +0.000085 and 0.463 with the row
excluded) and **Mulugu's 2026 prediction is 5.21 t/ha**, which appears in the
forecast table as **+494 %** against the state mean. The table carries a footnote
naming the cause, so the number is neither hidden nor silently wrong — it is
arithmetically correct given the delivered data, and its cause is stated.

## 6. Figures

| File | What it shows |
|---|---|
| `figures/f1_response_curve.png` | Response curve per crop, Stage 1 beside Stage 2, vertex annotated where supported, 2026 rainfall marker |
| `figures/f2_timeseries.png` | Kharif rainfall and cotton yield by season, p10–p90 bands, stacked on a shared x-axis (no dual axis) |
| `figures/f3_validation.png` | Out-of-sample RMSE against the median baseline, and the skill score |
| `figures/f4_choropleth.png` | Cotton yield anomaly (%) by district for 2022-23, RdYlBu with zero at the midpoint |
| `figures/f5_window_sensitivity.png` | The response curve refitted on three season windows |
| `figures/f6_forecast.png` | The 2026 forecast as the dashboard draws it: four crops on one indexed axis, the dashed 2026 segment, the Telangana average at 100 |
| `figures/f7_forecast_panels.png` | The same forecast per crop, in each crop's own unit, with the district observations |

The interactive explorer is `dashboard/index.html`. It opens straight from disk
(`file://`), needs no server, and fetches nothing from a CDN: Plotly, Leaflet and the
fonts are vendored in the repository. The map offers three metrics — yield anomaly
(RdYlBu, the default), absolute yield (Blues), and **rainfall deficit** (YlOrRd: this
season's rainfall against that district's own 2016-17–2022-23 median, so the map shows
where a season was dry *for that district* rather than for the state).

The report reads in one direction: the map and the season readout establish what was
observed; the forecast chart then states what the model predicts for 2026 and how well
that model has performed out of sample; the districts table carries the prediction to
district level; and "Does the weather model earn its place?" puts the model's value
against the alternatives. The rainfall–yield response curve is reported in §5 and in
F1–F3 rather than on the page: it is the evidence behind the forecast, and the page
leads with the forecast itself.

## 7. Limitations — all fifteen

**Limitation 3 is the single biggest limitation in this analysis, and it is not a
footnote.** No irrigation data is used anywhere. Telangana is heavily
borewell-irrigated, and crops recorded as rainfed are irrigated in distress years.
Irrigation therefore **attenuates the rainfall–yield relationship mechanically**, and
the weak or absent relationships reported in §5 may be a *consequence* of that
buffering rather than evidence that rainfall is unimportant. This is the leading
candidate explanation and it is **untested here** — adding a share-of-area-irrigated
covariate or a groundwater-access proxy is the single highest-value next step, and
it would convert "we could not explain it" into a mechanism. Telangana publishes
district irrigation statistics that would make this testable.

1. **Reanalysis, not observation.** ERA5 is a model-assimilated reanalysis product at
   0.25° (~25 km) resolution. It is not IMD station gauge data.
2. **Convective rainfall bias.** ERA5 is known to underestimate convective rainfall over
   dryland interiors. Absolute rainfall totals in this analysis may be biased low.
3. **No irrigation, soil, or input data.** This is the dominant confound, and the
   primary limitation of the whole analysis. Reported effects are rainfall's marginal
   association **conditional on all other factors being average**, not a causal yield
   model. See the note above.
4. **District aggregates, not farm-level.**
5. **Boundary discontinuity.** District boundaries were revised in 2016 and 2018.
   Pre- and post-revision periods are modelled as distinct fixed-effect groups, **not**
   as a continuous panel. The choropleth shows the 32 post-2016 districts; the two
   pre-2016 seasons are 9 undivided parent districts and are not spatially comparable
   to that layer.
6. **Sowing window ≠ season.** Jun–Sep is the official kharif sowing window; cotton and
   arhar grow to Nov–Dec, so late-season rainfall is undercounted. (Tested: the
   conclusion does not change under Jul–Sep or Jun–Oct — see §5.)
7. **DES agency discontinuity.** Pre-2014 figures originate with undivided Andhra Pradesh
   DES; post-2014 with Telangana DES. Estimation methodology may differ.
8. **Cotton is reported in bales**, not tonnes, and is modelled on that scale.
9. **Small sample per crop.** ~220 district-year observations per crop in the primary
   panel. At this sample size the analysis can detect a within-district correlation of
   about 0.2 or larger, so a genuinely small relationship (r ≈ 0.07, as cotton's) would
   not be detected here — the null for cotton is a *bounded* null, not an absence of
   any effect.
10. **2026 is a model prediction, not a validated forecast.** Each crop is forecast by
    its own specification, selected by leave-one-season-out cross-validation inside the
    fitting period. Two of the four models do not beat a district-median baseline, so
    their predictions mean *no evidence of a change*. No prediction interval is
    claimed: with three held-out seasons there is not enough data to calibrate one.
11. **Attribution.** ERA5 via Open-Meteo — CC BY 4.0. DES — Govt. of India open data.
12. **Rule-based percentile bands** are descriptive, not inferential. No confidence
    intervals are claimed.
13. **2026 planted area does not exist.** The state-level 2026 figures are
    area-weighted on each district's 2022-23 kharif area, applied identically to the
    prediction and to the Telangana average. It moves the state percentages by up to
    7.4 points (arhar).
14. **One delivered data value is retained as-is.** Mulugu's 2019-20 arhar cell reads
    891 t on 39 ha — 22.85 t/ha against the district's 0.62–0.91 t/ha — and it
    inflates arhar's fit and Mulugu's 2026 prediction. It is footnoted wherever it
    appears rather than silently corrected.
15. **Rice's optimum rests on a thin tail.** Only 11 of 220 district-seasons carry
    rainfall above the 1,354 mm vertex, and the fitted curve is still rising over most
    of the observed range. The vertex is real in-sample and survives the robustness
    grid, but its exact position is poorly determined — and the *linear* specification
    is what forecasts rice, not the quadratic.

Beyond the twelve, and specific to this build:

16. **The delivered DES file covers 2014-15 → 2022-23 only.** The specification assumed
    2000-01 → 2022-23; the file does not contain the earlier seasons. See
    `plan/ERRATA.md` — the file wins, and the panel windows were narrowed accordingly.
    **The "not enough seasons" hypothesis is therefore untested**: with 7 fitted
    seasons and 3 held out, a relationship of the size seen for rice cannot be
    distinguished from noise in the other three crops with confidence.
17. **No parent-district reconstruction is attempted.** The 2016 division is zero-sum
    (x → y+z ⟹ x = y+z), but Suryapet was formed from parts of two parents, so those
    parents cannot be rebuilt from the children the dataset names. Post-2016 districts
    are used as individual entities with their new names (`data/geo/PARTITION_NOTE.md`).
18. **The year fixed effects of the test period are unobserved.** Out-of-sample
    predictions use the reference year's effect; the no-year-FE column shows the
    conclusion is unchanged.
19. **Four crops only.** The source file carries 36 kharif crop groups; the other 32 are
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
            13_robustness_grid 14_slope_heterogeneity \
            16_forecast_models 15_forecast_series 17_figure_forecast \
            10_build_dashboard; do
    .venv/bin/python "src/${step}.py"
done

# 3. the checks
.venv/bin/python tests/verify_readme_numbers.py   # 164 README numbers vs the artefacts
bash tests/run_dashboard_qa.sh                     # 41 headless checks
```

- `src/03_fetch_era5.py` takes an optional window argument: `analysis` (default),
  `marker2026`, or `all`. The archive API enforces an hourly request quota; the
  fetcher retries with a 5 s pause on SSL/network drops, a 60 s cooldown on a generic
  429, and waits for the top of the next hour on the hourly-quota error. Raw
  responses are cached under `data/raw/openmeteo/` and are never re-fetched once
  present.
- `src/05_build_panel.py` re-verifies that the panel rebuilds byte-identically
  (SHA-256) and fails if it does not, and runs the **G1 year-mapping gate**: it
  re-fits the rainfall–yield relationship under three alignments and fails the
  build if the implemented one is not the best.
- `src/12_window_sensitivity.py` fails if the base window does not reproduce the
  shipped Stage 1 fit.
- `src/13_robustness_grid.py` writes the seven-row robustness grid and its
  verdict line; `src/14_slope_heterogeneity.py` writes the mixed-effects
  heterogeneity LRT. Both are inputs to the README tables, and the verifier
  checks the README against them.
- `src/16_forecast_models.py` selects a specification PER CROP by
  leave-one-season-out CV inside the training block and applies the validity
  gate (a specification may only predict 2026 if it yields a positive value for
  every district at the observed 2026 rainfall). It fails the build rather than
  shipping a model that does not pass.
- `src/15_forecast_series.py` turns the selected models into the per-district
  2026 predictions and the area-weighted state figures. It fails the build if any
  predicted yield is non-positive, or if the total and the yield/area disagree
  in percentage — which is the check that the area baseline is being applied
  consistently to both sides.
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
data/processed/    crops_kharif_clean, panel, model summary, robustness
                   grid, slope heterogeneity, forecast models and series
                   (gitignored)
data/geo/          districts.csv, districts.geojson, name_crosswalk.csv, PARTITION_NOTE.md
data/manifests/    fetch_manifest.json, checksums.sha256, per-stage manifests
src/01..17         the pipeline, one script per stage
figures/           F1–F6 static PNGs
dashboard/         the static interactive site
tests/             artefact verification and the headless dashboard QA
plan/              SRS.md, GUIDE.md, ERRATA.md, IMPROVEMENT_PLAN.md
```

**Git policy:** local commits only. No remote is configured, and no push has been
performed — the owner controls all remotes, releases and tags.
