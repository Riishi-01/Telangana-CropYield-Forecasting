# ERRATA — where the delivered data disagrees with the specification

**Recorded:** during the Tier 1 build of `telangana-agromet`.
**Rule applied:** `SRS.md §4.1` — *"The DES file is authoritative. Where this SRS and
the file disagree, the file wins and the discrepancy is logged."* Everything below is
logged here, and the affected SRS clauses are amended in place.

---

## C1 — the delivered yield file covers fewer seasons than the SRS assumed

| | |
|---|---|
| **SRS said** | Coverage 2000-01 → 2022-23 (§3.1); district counts 10 / 9 / 9 / 30 / 32 across five periods (§4.2) |
| **The file contains** | **2014-15 → 2022-23 only** — 9 seasons, 238 district-year rows, 32 districts |
| **Missing** | 2000-01 (Hyderabad reported separately) and 2001-02 → 2013-14 entirely |

**Resolution.** The primary panel is **2016-17 → 2022-23** (32 post-reorganisation
districts, 7 seasons). The extended panel is **2014-15 → 2022-23** with era-tagged
district ids; 2014-15 and 2015-16 are the only pre-2016 seasons available, covering 9
old-boundary districts. The weather ingest window moves to **2014-06-01 → 2023-10-31**.

**Consequences.**

- The "~220 district-year observations per crop" in `SRS §9` disclosure 9 still holds
  (Cotton 220, Rice 220, Arhar/Tur 219, Moong 209 in the primary panel).
- The chronological split is unchanged in shape: train 2016-17 … 2019-20 (4 seasons),
  test 2020-21 … 2022-23 (3 seasons).
- No pre-2016 parent-level data exists in the file, so `SRS §4.3`'s partition question
  is moot in addition to being unresolvable (see C4).
- The 2026 marker (§5.6) is unaffected and is implemented.

**Amended:** `SRS §3.1` (coverage), `§4.2` (period table), `§5.1` (windows),
`§6.3` (manifest window), `§9` disclosure 9 (verified against the file).

---

## C2 — the parsed shape is (238, 111), not (365, 126)

| | |
|---|---|
| **SRS said** | `GUIDE §3.2` gate: shape `(365, 126)` |
| **The file parses as** | **`(238, 111)`** = State + District + Year + 36 crop groups × 3 metrics |

`pandas.read_html()` expands the HTML rowspans, so State and District arrive fully
populated. The file is an HTML document despite its `.xls` extension, exactly as
`SRS §3.3` states.

**Resolution.** The gate in `src/01_ingest_des.py` asserts `(238, 111)` and warns
loudly on any other shape.

**Amended:** `GUIDE §3.2` gate value.

---

## C3 — 36 kharif crop groups, two of them in bales

| | |
|---|---|
| **SRS said** | Crops listed in §5.3: Cotton (lint), Arhar/Tur, Moong(Green Gram), Rice |
| **The file contains** | **36 crop × season groups, all labelled Kharif** (no Rabi) |

Units come from the source column labels: 34 groups are `Production (Tonnes)` /
`Yield (Tonne/Hectare)`; **two are in bales** — `Cotton(lint)` and `Mesta`
(`Production (Bales)` / `Yield (Bales/Hectare)`). The `SRS §5.3` unit hazard is real
and is handled: the unit is parsed from the label, never assumed.

**Resolution.** Modelling scope is unchanged (3 primary crops + Rice). The remaining
31 groups are carried in the panel and the dashboard as map-and-describe layers, with
no fitted model — the dashboard labels them "(mapped, not modelled)".

**Amended:** `SRS §5.3` (add the full group list and the second bales crop).

---

## C4 — the 2016 division is zero-sum; the earlier "blocked" verdict is withdrawn

`SRS §4.3` flagged the 2016 reorganisation as a possible hard blocker for parent
aggregation. It was checked, and the flag was over-stated. The finding:

1. **A district division is zero-sum.** When an undivided district *x* was divided
   into *y* and *z* in 2016, *x = y + z* — the land does not leave the parent, so the
   children's area and production sum to the parent's. A parent-level figure for a
   post-2016 season is therefore `sum(production_children) / sum(area_children)`.
2. **The children take the parent's name, or a new one.** Ranga Reddy → Rangareddy
   (spelling); Warangal → Warangal Rural + Warangal Urban; the rest keep their names.
3. **The dataset reports the children individually** from 2016-17 onward, and this
   analysis uses them as individual entities — which is how the data is delivered.
4. The reconstruction is **not attempted**, for two reasons: Suryapet was formed from
   parts of two parents (Khammam and Nalgonda), so those parents cannot be rebuilt from
   the children the dataset names without silently misstating them; and it is
   unnecessary, because no pre-2016 district is ever compared to a post-2016 one as if
   they were the same unit — era-tagged fixed effects keep the two apart.

**The zero-sum status is a fact of the reorganisation, not a measurement.** An
area-based check was attempted and was inconclusive: comparing a parent's kharif area
with the sum of its children's area across the 2015-16 / 2016-17 boundary gives
residuals of **+65 % to −70 %**, because crop choice reallocates area between districts
and seasons by more than the boundary effect. Crop area cannot test a boundary mapping.

The earlier verdict in `data/geo/PARTITION_NOTE.md` — "not a clean partition, Tier 2
blocked" — is **withdrawn**. Resolution recorded in `data/geo/PARTITION_NOTE.md`.

**Amended:** `SRS §4.3` RESOLVED block, `README §8` and limitation 14.

## C5 — the district boundary source

`SRS §7.4` records three previously attempted GeoJSON URLs returning 404. A working
source was found and is recorded with its checksum:

```
https://raw.githubusercontent.com/gpavanb1/Telangana-Visualisation/master/data/Telangana.geojson
SHA-256 e228271e9929f716…  →  data/manifests/geo.json
```

33 features: 32 used, plus Hyderabad. **13 DES district names differ from the boundary
file's spelling** (`Jangoan` → `Jangaon`, `Mahbubnagar` → `Mahabubnagar`, `Medchal` →
`Medchal Malkajgiri`, `Rangareddi` → `Rangareddy`, `Warangal` → `Warangal Rural`, and
others). The join is made explicit in `data/geo/name_crosswalk.csv` with the method
recorded per row — 19 exact after normalisation, 13 by alias table, 32 of 32 joined.

Hyderabad has no yield observation in the delivered file, so it is carried as an
explicit **no-data** feature: the map shows a labelled gap rather than an unexplained
hole.

**Amended:** `SRS §7.4` (boundary source, now recorded with a checksum).

---

## C6 — the archive API resolves requests to a nearby grid node, and enforces an hourly quota

Two operational findings during the weather ingest, both now handled in
`src/common.py` and `src/03_fetch_era5.py`:

1. **The API does not echo the requested coordinate back.** It resolves the point to
   the surrounding ERA5 grid node, which can sit up to half a cell (0.125°) from the
   request. The block-count check is therefore paired with a half-cell coordinate
   tolerance (0.15°), and the deviation is recorded per fetch in the manifest. Adjacent
   districts (Warangal / Warangal Urban, ~0.27° apart) are far enough apart that the
   tolerance cannot mask an off-by-one shift.
2. **The free tier enforces an hourly request quota.** The endpoint answers
   `429 {"reason": "Hourly API request limit exceeded. Please try again in the next
   hour."}`. The retry harness therefore waits for the top of the next hour on that
   error, rather than hot-looping. The 2026 marker window is fetched in a single
   multi-coordinate request to reduce the number of calls.

The `GUIDE §4.1` retry contract (8 attempts, 5 s pause on network/SSL failure) is
implemented as specified and extended with the 429 handling above.

---

## C7 — colour semantics of the anomaly ramp

`SRS §7.1` fixes the anomaly colormap as `RdYlBu` and states the semantics as
**blue = below normal, cream = normal, red = above normal**. Matplotlib's `RdYlBu`
runs red → blue as the value increases, so the ramp is used **reversed**
(`RdYlBu_r`); the underlying colormap is unchanged and the legend labels the
direction explicitly ("blue = below normal, red = above normal"). Zero is pinned to
the exact midpoint by a symmetric `Normalize(vmin=-M, vmax=+M)`, and the domain is
fixed per crop across every season so the map never rescales between views.

Absolute yield, which is a secondary toggle, uses a single-hue sequential ramp
(`Blues`) so that the red ramp is never used to mean "good".

**Amended:** `SRS §7.1` (reversal noted).

---

## C8 — the project scope is four crops, and the yield is modelled at full precision

The owner fixed the scope: **Telangana, kharif, 2014-15 to 2022-23, four crops** —
Cotton (lint), Arhar/Tur, Moong (green gram) and Rice. The source file carries 36
kharif crop groups; the other 32 are removed in ingest, together with the constant
`State` column, the redundant `Year` column, the always-Kharif `session` column and
the 3-level MultiIndex header. The delivered dataset is now
`data/processed/crops_kharif_clean.csv` — **940 rows x 13 columns** — with 12 rows
removed by the quality rules (for these four crops only *area < 10 ha* and missing
values bite), every removed row listed with its reason in
`crops_kharif_clean.metadata.json`.

**Precision.** The DES publishes yield rounded to two decimals. The dataset keeps
that value as `yield_reported` and carries `yield = production / area_ha` at full
precision as the modelling target, because 2 dp is a coarse grid for moong (a 0.01
step on a median of 0.63 t/ha is 1.6 %, the same order as the effects being
measured). A hard gate asserts `yield == round(yield_reported, 2)` on every row and
it passes on all 940. DATA_VERSION moves 1.0.0 -> **1.1.0** (no schema break in
the panel, a precision change in the response).

**Units** are read from the source column labels and never converted: cotton in
bales, the other three in tonnes, area in hectares. No bale-to-tonne factor is
applied - it would be an assumption, not a cited value in this file - and
cross-crop comparability comes from percentage effects, not a converted scale.

**A note on the 2026 percentile.** Rainfall is a district-season variable, so the
historical distribution it is compared against counts each district-season once,
not once per crop. On that basis the 2026 state-mean kharif rainfall (488 mm) sits
at the **1.4th percentile** of the fitted period, and 9 of 32 districts fall below
the observed minimum.

---

## C9 — the hardening pass: the year mapping is verified, the fixed effect is renamed, and the result is a split

Implements `plan/IMPROVEMENT_PLAN.md`. Four substantive changes, plus the
correction of two factual errors in that plan (recorded in its §0 V-0).

**C9.1 — the agricultural-year mapping is verified in code, not assumed.**
`common.YEAR_MAPPING` names the convention ("season Y-YY == Jun-Oct of calendar
year Y") and `common.verify_year_mapping()` is an **executable gate** that
re-fits the rainfall–yield relationship under three alignments and fails the
build if the implemented one is not the best. It passes: mean |r| is 0.137
(same year) against 0.107 (+1 yr) and 0.037 (−1 yr), and **rice's correlation
flips sign** under the +1-yr shift. The Mahbubnagar 2015-16 spot-check row is
printed at build time. This closes the plan's highest-priority item: the
mapping is correct, so the result set is not void.

**C9.2 — the year fixed effect is renamed.** The term was `C(season)`, which
invites a reviewer to believe kharif-vs-rabi variation was controlled for. Only
kharif is modelled, so the term is a **year** effect. The panel column
`season_year` is renamed `year`; the model term is `C(year)`; the specification
key `no_season_fe` becomes `no_year_fe`; and the prose now says "year fixed
effects" everywhere. The design matrix is **numerically identical** before and
after (verified), and the fitted coefficients are unchanged to the last
reported digit. Per SRS §6.2 a column rename is a MAJOR schema change, but the
panel's *content* is unchanged, so DATA_VERSION stays at 1.1.0 and the change
is recorded here instead.

**C9.3 — the result is a split, not a blanket null, and is now reported that
way.** The plan's §0 was written on the assumption that no crop showed a
rainfall–yield relationship. The rice relationship is real: within-district
r = +0.221 (p = 0.001), the quadratic term p = 0.018, and it survives the
robustness grid. The README's headline has been rewritten accordingly.

**C9.4 — the 2026 implied yield is published only where it is defensible, and
only as a band.** Two gates were added. (a) The implied range is published only
for a crop whose curve has a statistically supported shape — the same rule that
gates the vertex. For arhar, whose quadratic term is not significant, the
reading returned **negative yields for 6 of 32 districts**, which is
physically impossible; that number is now withheld and the dashboard says why.
(b) What *is* published is a **band** (the range of readings across the 32
districts), never a single dashed assertion. For rice the band is −12.7 % to
−4.9 % of each district's own normal, with the state-mean reading (−9.9 %)
inside it.

**Corrections to the improvement plan itself, recorded in its §0 V-0:**
P1-10 asserted that 2001-02 → 2013-14 data exists in the delivered file — it
does not, and P1-10 is dropped as untestable. P1-7 asserted that kharif rainfall
"essentially never exceeds ~900 mm" — the observed range is 363–1,827 mm, and
11 of 220 district-seasons exceed the rice vertex, so the vertex is thin-tailed
rather than extrapolative. Both are corrected in the plan.

**Also implemented:** the robustness grid (P1-6, `src/13_robustness_grid.py`,
7 rows with a verdict line), the mixed-effects slope heterogeneity test (P1-9,
`src/14_slope_heterogeneity.py`, LRT p-values for all four crops), the Okabe-Ito
crop identity palette (P4-16, SRS §7.1), the 2026 band rendering (P4-15), the
boundary-discontinuity note on the map itself (P4-17), and the irrigation
absence stated as the primary limitation (P2-11, the A23 path).

---

## C10 — the 2026 predicted yield is now IN SCOPE, and the measure is yield per hectare

**Owner decision, 2026-10-22.** This supersedes C9's "2026 is a diagnostic, not a
forecast" and the corresponding prohibition in SRS §2.2 and IMPROVEMENT_PLAN P3-12.
Those prohibitions are retained above as history; what follows is what now governs.

**C10.1 — scope.** A predicted-yield display is in scope. SRS §2.2's entries "Live
2026 yield forecasting" and "Any prediction of yield for years not covered by DES
observations" are withdrawn. What is still prohibited: production totals presented
as an independent claim, a "rainfall −x% → yield −y%" chaining, and any 2026
figure published for a crop whose model has no statistically supported shape.

**C10.2 — one model per crop.** The single shared specification is replaced by a
per-crop selection. Four candidate specifications are scored by leave-one-season-out
cross-validation INSIDE the training block; the validation block is evaluated once,
after selection, so the reported skill is not a selection statistic. A second gate
applies: **a specification may only predict 2026 if it produces a positive yield for
every district at the observed 2026 rainfall.** Arhar's quadratic passes the first
gate and fails the second — its curve goes negative below ~440 mm, the 2026 state
mean is 488 mm, and it returns negative yields for 19 of 32 districts. The
rejection and its reason are recorded, not silently dropped.

| Crop | Selected | Test skill (selected) | Test skill (shared spec) |
|---|---|---|---|
| Cotton (lint) | linear | **−0.235** | −0.405 |
| Arhar / Tur | linear (quadratic rejected on validity) | **+0.006** | +0.033 |
| Moong (green gram) | linear | **−0.017** | −0.023 |
| Rice | linear | **+0.078** | −0.111 |

Rice's forecast skill improves from −0.111 to +0.078. The quadratic remains a
FINDING for rice (β₂ p = 0.018, R* = 1,354 mm) but is not the model used to
predict; the two are reported separately and the reason is stated.

**C10.3 — the measure is yield per hectare, area-weighted.** A production total
mixes productivity with land utilisation. Every level is therefore built as a
yield per hectare, and every aggregation to the state is **area-weighted**:
`SUM(area_i × yield_i) / SUM(area_i)`. The unweighted mean of district yields is
NOT used anywhere: rice district area spans 180× (720 ha to 129,633 ha per
district-season), so an unweighted mean weights a 720 ha district the same as a
129,633 ha one. On the reference period this choice moves arhar's state figure by
13.6 % and flips the sign of its 2026 comparison.

**C10.4 — the 2026 area baseline.** 2026 planted area does not exist and cannot be
forecast. Each district's **2022-23 kharif area** is the baseline, applied
IDENTICALLY to the 2026 prediction and to the Telangana average, so the comparison
isolates yield from land utilisation. The assumption is stated in the artefact, the
README and on the dashboard. It moves the state percentages by up to 7.4 points
(arhar), which is why it is stated rather than buried.

**C10.5 — the 2026 state figures** (area-weighted, 2022-23 area on both sides):

| Crop | 2026 yield/area | Telangana average | Δ per ha | Δ % | Δ total |
|---|---|---|---|---|---|
| Cotton (lint) | 2.029 bales/ha | 2.645 | −0.615 | −23.3 % | −1,245,059 bales |
| Arhar / Tur | 0.837 t/ha | 0.771 | +0.066 | +8.6 % | +15,057 t |
| Moong (green gram) | 0.756 t/ha | 0.618 | +0.138 | +22.4 % | +3,734 t |
| Rice | 3.151 t/ha | 3.327 | −0.176 | −5.3 % | −462,623 t |

**C10.6 — a delivered data value is retained and is visible.** Mulugu's 2019-20
arhar cell reads 891 t on 39 ha (22.85 t/ha) against the district's 0.62–0.91 t/ha
in its other years; it is almost certainly a decimal error in the DES file. The
owner elected to keep the file exactly as delivered, so the row stays: arhar's
model keeps its degraded fit (b₁ = −0.000150, R² = 0.235, against +0.000085 and
0.463 with the row excluded) and Mulugu's 2026 prediction is 5.21 t/ha, which
appears in the forecast table as **+494 %** against the state mean. The table
carries a footnote naming the cause, so the number is not hidden and not silently
wrong — it is arithmetically correct given the delivered data, and its cause is
stated.

**C10.7 — the disclosure set grows from 12 to 15.** The new entries cover the
forecast method and its skill, the 2026 area baseline, and the absence of a
prediction interval (with three held-out seasons there is not enough data to
calibrate one honestly).

---

## C11 — the dashboard leads with the forecast: one chart, and the response curve retires

**C11.1 — the response curve is retired from the page.** The "Rainfall → yield
response" section is removed from the dashboard and replaced by the forecast
chart. The response curve remains in the analysis (README §5, figures F1–F3): it
is the *evidence* behind the forecast, and the page now leads with the forecast
itself. The season readout keeps the model facts — the rainfall effect, the
curvature, the optimum R\* and its p-value — so the evidence is still on the
page, in words.

**C11.2 — the forecast becomes ONE chart with a crop selector.** The four small
multiples are replaced by a single chart: nine observed seasons and then 2026,
with a selector offering **All crops** or one crop, and the crop names behaving
as ticks. Clicking a crop focuses the chart on it and reveals the district
observations behind the line; clicking **All** ticks every crop. The forecast
districts table is unchanged, including its "2026-27 · 32 districts · bales/ha"
subtitle.

**C11.3 — the axis is indexed, and the state line is area-weighted.** Cotton is
in bales per hectare and the other three in tonnes, so four crops cannot share a
raw axis. Each crop is indexed to **its own Telangana average over the fitted
period (2016-17 → 2022-23 = 100)** — the same area-weighted reference the
forecast table uses — so the 2026 endpoint reads directly as the forecast
difference (cotton 76.7, arhar 108.6, moong 122.3, rice 94.7).

The state line changes from the **unweighted district median** to the
**area-weighted state yield per hectare** (`SUM(area × yield) ÷ SUM(area)`).
This is a substantive improvement, not a cosmetic one: the area-weighted figure
is a state total divided by a state area, so it is the same quantity on both
sides of the 2016 reorganisation, and the line therefore runs through 2014-15
without a break. The median is not comparable across that boundary. The
unweighted mean of district yields remains unused, as C10.3 requires.

**C11.4 — the 2018-19 districts table is retired.** The observed-season
districts table is removed from the page. Per-district observation for the
selected season remains on the map, per-district 2026 predictions remain in the
forecast table, and the CSV export still ships the same rows.

**C11.5 — the scale rule.** In the focused (single-crop) view the y range is
set by the state line, the 2026 prediction **and the 2nd-to-98th percentile of
the district observations** — a percentile, not the extremes. One delivered
value (Mulugu, arhar 2019-20) would otherwise flatten the chart, and the raw
minimum and maximum would let a single district decide the scale. Observations
outside the range are counted and reported under the chart; none is deleted.
In the "all crops" view there are no district points, so the range is the state
line and the prediction alone.

**C11.6 — the language.** "Does the weather model earn its place?" is the
heading for the model-comparison section in both the report and the page, and
the report's register is technical but plain: *model specification*, *holdout
period*, *out-of-sample skill score*, *area-weighted*, *baseline*.

---

## C12 — the map opens on the 2026 prediction, and the state gets a five-row summary

**C12.1 — the 2026 prediction becomes a season on the map.** The season
selector gains `2026-27 (prediction)` as its last option, and it is the
default, with cotton and absolute yield. There are no 2026 yield
observations, so every value under that option is a model prediction, and the
map note, the hover card and the season readout all say so. The three map
metrics all work in the layer and none of them is faked: the yield metric
colours the predicted yield per hectare, the anomaly metric colours the
prediction against **that district's own** observed mean yield, and the
rainfall-deficit metric colours the 2026 rainfall against that district's own
median rainfall.

**C12.2 — the 2026 layer has its own fixed domain.** The observed map uses one
fixed domain per crop, so the scale never moves between seasons or districts.
The 2026 predictions occupy the middle of the observed range — cotton spans
1.45–3.02 bales/ha inside an observed 0.22–4.90 — so on the observed domain
they would all land in one pale band and the map would say nothing. The
prediction layer therefore has its own fixed domain per crop, still fixed
across the districts and never rescaled by the selection, and the legend
caption says which domain is in force.

**C12.3 — the season readout carries the 2026 point, dashed.** The kharif
rainfall chart takes the 2026 district band (p10 285, median 439, p90 731 mm)
from the ERA5 reanalysis; the crop yield chart takes the 2026 predicted band.
Both are drawn dashed, exactly as on the forecast chart, because nothing has
been observed for them, and the x-axis gains `2026-27` as its last category.
The season label `2026-27` is used everywhere on the page, including the
forecast chart's last category, which was `2026`.

**C12.4 — the state in one table.** Above the district table, and in the same
section, a five-row summary: the four crops and the kharif rainfall, each
against the Telangana average. The crop name is the parent header; 2026 and
the state average are the two columns under it. The change rides in the 2026
cell, beside the value, with the sign always printed and the colour carrying
the same vermillion/bluish-green convention as the district table below it.
All totals are in millions — with three decimals below 1 M, because moong is
20 thousand tonnes and two decimals would round it to nothing.

**C12.5 — the rainfall base, and the label that could not be true.** The
average column for rainfall is the **state-wise average kharif rainfall over
2014-15 to 2022-23** (848 mm), the mean of the nine seasonal state means,
against the 2026 state mean of 488 mm. That is **↓ 42.5 %**, and it is the
figure the report and the page both print. A label of "↓ 50 %+" was requested
and is not supportable against this base, or against any reading of a
2014-2022 state-wise average (the pooled nine-season district-season mean
gives −45.6 %, the mean of the nine season medians −41.4 %, the mean of the
nine area-weighted season figures −41.5 %). It is true only against 2022-23
alone (1,133 mm, −56.9 %), which is a different claim. The stronger true
statement is carried instead: **2026 is the driest kharif season in the
nine-season record**.

**C12.6 — the district table is untouched.** The `Districts · 2026-27 · 32
districts · bales/ha` table keeps its subtitle, its five columns, its sorting
and its click-through to the point-detail panel. The CSV export now also
carries the 2026 predictions when the prediction layer is selected.

---

## C13 — the page presents the forecast: the districts table, the disclosure list and the disclaimer box are retired

**C13.1 — the districts table is retired from the page.** The 32-row
`Districts · 2026-27 · 32 districts · bales/ha` table is removed, with its
sorting, its five-column header and its click-through. The section it lived
in is renamed **"2026 yield forecast Analysis"** and now carries the five-row
state summary alone.

The per-district 2026 numbers are not lost, but they are no longer a list you
can scan or sort side by side. They live in three places: the **map**, as
colour and as the number on each polygon; the **hover card**, which carries
the predicted yield per hectare, the state average, the difference against the
state, the 2026 rainfall, the deficit against that district's own median and
the 2022-23 area baseline; and the **CSV export**, which is the full 32-row
table as a download. The export is unaffected by the retirement: it builds its
rows from the data, not from the DOM.

**C13.2 — the disclosure list and the provenance footer are retired.** The
`What this is not` heading, the fifteen-item disclosure list and the
colophon provenance strip are removed from the page. The **README keeps all
fifteen disclosures** (§7 and §5.4), and SRS §9 is amended so that the
requirement reads "in the README" rather than "in the README and in any
derived document". The bundle still ships the disclosure set as the
machine-readable record of what applied to that build, and the verifier
asserts that the report carries every one of them.

**C13.3 — the boxed 2026 disclaimer is retired.** The vermillion box under
the forecast chart is removed. The page must still label 2026 as a
prediction, and it does, in six places: the season option reads
`2026-27 (prediction)`, the map note reads `2026-27 (prediction)`, the season
readout reads `2026-27 (prediction) · 32 districts predicted`, the hover card
reads `2026-27 · prediction`, the forecast chart's 2026 segment is dashed, and
the chart's foot states that the segment is a prediction and not an
observation, and prints every crop's out-of-sample skill score.

**This is the one change in the project's history that removes a caveat from
a published artefact rather than adding one.** The page now carries no
disclosure list and no boxed caveat. The report of record — the README —
carries all of it, and the chart's foot keeps the prediction framing, the
area-basis assumption and the skill caveat. It is recorded here so that the
decision is on the record rather than silent.

**C13.4 — the point-description panel loses its table trigger.** The panel
under the forecast chart is opened by clicking the 2026 diamond on the chart
or a district observation when a single crop is focused. The QA harness now
drives it through the real hover machinery and the click event Plotly emits,
rather than through a table row.

---

## C14 — the page loses its two analysis sections, the masthead is rewritten, and the hover label is fixed

**C14.1 — the season-window panel is retired from the page.** The section
*Does the rainfall optimum depend on the season window?* — the three-window
p-value and vertex matrix — is removed from the page, with its renderer, its
CSS and the `window_sensitivity` payload in the dashboard bundle.

The **analysis is unchanged and stays in the report of record**: README §5
("Season-window sensitivity") keeps the full matrix, and
`figures/f5_window_sensitivity.png` is still produced by `src/12_figure_window.py`
and still listed in the figure table. Only the page's copy is retired. The
artefact `data/processed/window_sensitivity.json` is still written by the
pipeline and the verifier still checks the README matrix against it, because
the README is the report.

**C14.2 — the model-comparison chart is retired from the page.** The section
*Does the weather model earn its place?* — the two-panel bar chart of ΔR²
(Stage 2 − Stage 1) and of the skill score against the median baseline — is
removed, with `renderStats()`, its CSS and its two `els` entries.

What it carried is not lost from the page: the per-crop ΔR² and skill scores
are in the **model readout** panel beside the map, and all four per-crop
forecast skill scores are in the forecast chart's foot. What is lost is the
side-by-side *comparison* of the four crops, which the README's skill table
still gives. The README's §5 heading is retitled to **"Can rainfall predict a
district's kharif yield?"**, which is what that section actually measures: the
model against the district's own ten-year median.

**C14.3 — the model readout now describes the model that produced the numbers
on screen.** This fixes a real inconsistency, not a wording one. The page
opens on the 2026 prediction layer, but the readout was describing the shared
Stage-1 quadratic fit — so for rice it showed b₁ = 0.001474 and a skill of
**−0.111**, while the map beside it was drawing the *linear* model's
prediction, whose skill is **+0.078**. Two skill numbers for the same crop on
one screen, and neither of them labelled as to which model it belonged.

On the 2026 layer the readout now carries that crop's forecasting model: the
specification as fitted (`yield ~ rain_mm + C(district_id) + C(year)`), the
estimator, the rainfall effect restated per 100 mm in the crop's own unit, R²,
the skill score against the district-median baseline with the verdict in words,
the fit and test seasons with their row counts, and the rejected specification
with its reason where there is one (arhar). On an observed season the readout
is unchanged: it describes the shared Stage-1 fit. The bundle gains the fields
this needs (train/test seasons, row counts) from `forecast_models.json`; no
model is refitted.

**C14.4 — the masthead is rewritten and the type scale is polished.** The
headline is now **"Forecasting kharif yield from rainfall and 2026
prediction"** on one line, and the standfirst is a labelled fact block instead
of a paragraph: place, period, crops, data source, predictive model — the
last of them naming the estimator as what it is (ordinary least squares with
district and year fixed effects; statistical, not machine learning) and saying
how it was chosen. The one-line rule is enforced by a width and a media query,
not by luck. The display type is reduced from `5.2rem` to `2.85rem` and the
section headings from `2rem` to `1.6rem` at their largest, because the old
scale put a three-word heading on two lines and a five-word one on four.

**C14.5 — the hover label no longer loses its text.** Plotly sizes a hover
label's box from the text it measures, and the text it then draws is not
always the text it measured. The label was measured in a narrow fallback face
and drawn in the page's own typeface, so the tail of the line spilled out of
the box — and on the old blue label that spill was **white on the cream page,
so the reader saw a box with the text stopping in the middle of a word**. It
was worst on the 2026 diamonds, at the right-hand edge of the chart, where the
label is long and the point is at the margin.

The fix is one shared `HOVER_LABEL` in the **layout** (Plotly reads
`hoverlabel` from the layout; a `hoverlabel` in the *config* is silently
ignored, which is why the first attempt at this fix did nothing): a cream box,
a hairline border, ink text, and the page's typeface. The measurement and the
drawing now agree, and even a spill would stay legible, because the text is
ink on the page's own surface colour rather than white on a crop colour.

**C14.6 — the yield-per-year chart is named for what it is.** The forecast
section's heading is now **"Yield per year, and the 2026 prediction"**.

---
---

## C15 — the reading defaults to rice, the foot is explained in headed items, and the hover label is lifted off the plot

**C15.1 — the reading panel opens on the rice 2026 prediction.** The panel
under the chart no longer starts empty with a prompt to click a point; it
starts on a reading. Rice, because it is the one crop whose model beats
its own baseline out of sample (+0.078), so the page opens on a prediction
that earned the right to be quoted. Cotton (−0.235) and moong (−0.017) are
one click away and their diamonds still carry the negative skill. Clicking
any point still replaces the reading; re-clicking rice's diamond leaves it.

**C15.2 — the row under the chart is one column until it has two things to
say.** The explanation and the reading share a row that is full width while
the reading is empty and splits once it is populated, so a build with no
forecast artefact leaves the explanation full width rather than sitting
beside an empty column. This is the one place on the page where the
method-selection procedure is **not** repeated: the foot says how to read
the axis, the state line, the 2026 segment and the skill scores; it does not
say how the specification was chosen.

**C15.3 — the chart foot is four headed items, not one paragraph.** "How to
read the axis", "The state line", "The 2026 segment" and "How well the
model does", each one or two sentences, the skill scores as a list rather
than a run-on. A reader who wants the axis rule should not have to read the
skill scores to find it. The off-scale note is a fifth item and only appears
when there are observations outside the plotted range.

**C15.4 — the hover label is lifted off the plot.** Plotly paints an opaque
box; what it cannot do is lift it, so over the lines a label read as a hole
punched in the chart. A drop shadow on the label's box path gives it an edge
and separates it from the series underneath. The detached-text capture that
prompted this was the font-swap race — a label measured against a fallback
face and drawn in the real one — which the shadow now hides rather than
hides-but-does-not-fix: the box is opaque, so the text is never read against
a line.

**C15.5 — the model readout panel is retired.** The panel beside the map is
removed, with `renderModelFacts()`, `forecastFacts()`, the `.facts` CSS and
the model icon. Its content moves to the two places that already exist: the
estimator is named in the masthead's *Predictive model* line, and the
per-crop specification, rainfall effect, skill and verdict are on the
reading panel, one click from any diamond. The page therefore states the
method once, in the masthead, rather than twice in panels that can disagree
— which is what produced C14's two skill numbers on one screen.

**C15.6 — the discipline is named where the data is.** The data-source line
reads **Agrometeorology (DES yields; ERA5 reanalysis rainfall through the
Open-Meteo archive API)**. The predictor line reads **Statistical model
(least squares with district and year fixed effects)** — method only, no
"not machine learning" editorialising, because the label already says what
kind of thing it is.

**C15.7 — the code stops narrating itself.** app.js carried 198 comment
lines. The four essay blocks — the hover-label rationale, the 25-line
forecast header, the font gate and the `SEASON_2026` note — are cut to their
load-bearing sentences, and the reasoning that made this codebase's numbers
defensible moves here rather than being deleted: the hover-label defect
(C14.5, C15.4), the indexing rule, the categorical-axis rule, the
area-weighting rule and the font gate are all recorded. Every surviving
comment answers *why*, none restates the line below it.

---
---

## Verification status

| Gate | Status |
|---|---|
| G2.1 district structure verified against the file | **PASS** — 9 / 9 / 30 / 30 / 32 × 5 (see C1) |
| G2.2 era-tagged district dimension | **PASS** — 41 district-era ids |
| G2.3 `PARTITION_NOTE.md` with an explicit verdict | **PASS** — division is zero-sum; no parent reconstruction attempted (C4) |
| G2.4 coordinates present, method recorded | **PASS** — 32/32, ERA5-grid area-weighted centroid |
| G2.5 boundary file joins to the district list | **PASS** — 33 features, 32/32 joined (C5) |
| G3.3 cotton present in bales/ha | **PASS** — 238 rows, `bales/ha` |
| G1 clean dataset identity gate | **PASS** — `yield == round(yield_reported, 2)` on all 940 rows |
| G4.5 weather cached raw + interim | **PASS** — 113,984 district-days, 0 % NaN, contiguous |
| G6.3 panel rebuilds byte-identically | **PASS** — identical SHA-256 across two builds |
| G7.3 both FE specifications reported | **PASS** — 4 crops × 4 specifications |
| G8 ΔR² reported for every modelled crop | **PASS** — including the null results |
| G9 chronological split; skill reported at any sign | **PASS** — 3 of 4 crops negative |
| G10 F1–F4 exist; no dual axis; no jet/rainbow; greyscale-checked | **PASS** |
| G11 dashboard QA | **PASS** — 58 headless checks |
| G12 all 15 disclosures present | **PASS** — in README §7 and in the dashboard footer |
| **G1 year mapping verified (C9.1)** | **PASS** — executable 3-alignment gate; same-year is the best fit |
| **G2 no "season effects" wording (C9.2)** | **PASS** — 0 hits for `season (fixed )?effect` in `src/`, `README.md`, dashboard |
| **G3 fitted range stated (P0-3)** | **PASS** — `model_summary.json` and `fetch_manifest.json` both record it |
| **G4 partition verdict per district (P0-4)** | **PASS** — 32 post-2016 districts listed in `PARTITION_NOTE.md` |
| **G6 robustness grid (P1-6)** | **PASS** — 6 cells run, row 7 deferred, verdict line in README §5 |
| **G9 heterogeneity LRT (P1-9)** | **PASS** — p reported for all 4 crops; shared slope not rejected |
| **G11b 2026 implied range gated (P4-15)** | **PASS** — published for rice only; 3 crops withheld with a reason |
| **G11c per-crop forecast model (C10.2)** | **PASS** — CV selected on train only; arhar's quadratic rejected on validity; 0 negative predicted yields |
| **G11d state figures area-weighted (C10.3)** | **PASS** — the total and the yield/area agree in percentage by construction |
| **G11e 2026 area baseline stated (C10.4)** | **PASS** — 2022-23 area, applied identically to both sides |
| **G11f one forecast chart, indexed (C11.2, C11.3)** | **PASS** — 1 chart, All + 4 crop ticks, 10 x categories with 2026 last, 4 dashed 2026 segments |
| **G11g the retired sections are gone (C11.1, C11.4)** | **PASS** — no `#curveChart`, no `#districtTable`, no `#forecastGrid` in the DOM |
| **G11h the 2026 districts table is kept (C11.2)** | **SUPERSEDED (C13)** — retired from the page in v1.2.1; the per-district numbers are on the map, in the hover card and in the CSV |
| **G11i the map opens on the prediction (C12.1)** | **PASS** — default season 2026-27 (prediction), cotton, absolute yield |
| **G11j the state summary agrees with the artefacts (C12.4)** | **PASS** — 5 rows; every 2026 and average total matches `forecast_series.json` |
| **G11k the rainfall base and label (C12.5)** | **PASS** — 848 mm base from `rain_state`; 488 mm is −42.5 % |
| **G11l the districts table is retired (C13.1)** | **PASS** — no `#forecastTable` in the DOM |
| **G11m the disclosure footer and the disclaimer box are retired (C13.2, C13.3)** | **PASS** — no `#disclosureList`, no `footer.colophon`, no `#markerDisclaimer` |
| **G11n the page still labels 2026 as a prediction (C13.3)** | **PASS** — the season option, the map note, the readout note and the hover card all carry it |
| **G11o the window panel is retired from the page (C14.1)** | **PASS** — no `#windowHead`, no `#windowTable`, no `renderWindowPanel`, no `window_sensitivity` in the bundle; the README matrix and F5 are untouched |
| **G11p the model-comparison chart is retired from the page (C14.2)** | **PASS** — no `#statsHead`, no `#statsChart`, no `renderStats`; the README §5 skill table and the renamed heading remain |
| **G11q the readout describes the forecasting model (C14.3)** | **PASS** — on the 2026 layer it names the specification, the per-100-mm effect, R², the skill and the verdict; on an observed season it names the Stage-1 fit |
| **G11r the masthead is one line and the type scale is polished (C14.4, C14.6)** | **PASS** — the headline does not wrap at 1500px; the standfirst names place, period, crops, source and estimator |
| **G11s the hover label keeps its text (C14.5)** | **PASS** — the label is styled in the layout; the text fits inside its own box on every trace, checked with a real hover on the state lines, the diamonds and a district point |
| **G11t the reading defaults to the rice prediction (C15.1)** | **PASS** — the panel is populated on load with the rice 2026 reading and 8 fields; a click still replaces it |
| **G11u the foot is headed items (C15.3)** | **PASS** — 4 sub-headings on the page, one skill row per crop, the axis rule stated |
| **G11v the hover label is lifted off the plot (C15.4)** | **PASS** — `drop-shadow` is applied to the label's box path and computed as a filter |
| **G11w the model readout is retired (C15.5)** | **PASS** — no `#modelFacts`, no `renderModelFacts`, no `.facts` in the stylesheet |
| **G11x the discipline and the estimator are named (C15.6)** | **PASS** — the data-source line reads Agrometeorology; the predictor line names least squares with district and year fixed effects |
| G13 local commits clean; no push | **PASS** — no remote configured |
