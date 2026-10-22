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
| G11 dashboard QA | **PASS** — 20 headless checks |
| G12 all 12 disclosures present | **PASS** — in README §6 and in the dashboard footer |
| G13 local commits clean; no push | **PASS** — no remote configured |
