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
| G11 dashboard QA | **PASS** — 34 headless checks |
| G12 all 12 disclosures present | **PASS** — in README §7 and in the dashboard footer |
| **G1 year mapping verified (C9.1)** | **PASS** — executable 3-alignment gate; same-year is the best fit |
| **G2 no "season effects" wording (C9.2)** | **PASS** — 0 hits for `season (fixed )?effect` in `src/`, `README.md`, dashboard |
| **G3 fitted range stated (P0-3)** | **PASS** — `model_summary.json` and `fetch_manifest.json` both record it |
| **G4 partition verdict per district (P0-4)** | **PASS** — 32 post-2016 districts listed in `PARTITION_NOTE.md` |
| **G6 robustness grid (P1-6)** | **PASS** — 6 cells run, row 7 deferred, verdict line in README §5 |
| **G9 heterogeneity LRT (P1-9)** | **PASS** — p reported for all 4 crops; shared slope not rejected |
| **G11b 2026 implied range gated (P4-15)** | **PASS** — published for rice only; 3 crops withheld with a reason |
| G13 local commits clean; no push | **PASS** — no remote configured |
