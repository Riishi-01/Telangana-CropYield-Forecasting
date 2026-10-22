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

## C4 — the partition constraint is confirmed, and is moot for this file

`SRS §4.3` required the 2016 reorganisation to be checked before any parent
aggregation. Two findings:

1. The reorganisation is **not** a clean partition — a child district drawing
   territory from two parents (Suryapet from Khammam and Nalgonda; Vikarabad and
   Narayanpet have similarly mixed origins) admits no exact zero-sum partition of
   parents into children. **Tier 2 (parent reconstruction) is blocked.**
2. The delivered file contains **no pre-2016 parent-level data**, so there would be
   nothing to reconstruct from in any case.

**Resolution.** `data/geo/PARTITION_NOTE.md` records the verdict, the sources consulted
and the reasoning. Tier 1 proceeds with era-tagged district ids
(`{slug}__pre2016` / `{slug}__post2016`). No parent aggregation is attempted anywhere
in the code.

---

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

## Verification status

| Gate | Status |
|---|---|
| G2.1 district structure verified against the file | **PASS** — 9 / 9 / 30 / 30 / 32 × 5 (see C1) |
| G2.2 era-tagged district dimension | **PASS** — 41 district-era ids |
| G2.3 `PARTITION_NOTE.md` with an explicit verdict | **PASS** — Tier 2 blocked (C4) |
| G2.4 coordinates present, method recorded | **PASS** — 32/32, ERA5-grid area-weighted centroid |
| G2.5 boundary file joins to the district list | **PASS** — 33 features, 32/32 joined (C5) |
| G3.3 cotton present in bales/ha | **PASS** — 238 rows, `bales/ha` |
| G4.5 weather cached raw + interim | **PASS** — 113,984 district-days, 0 % NaN, contiguous |
| G6.3 panel rebuilds byte-identically | **PASS** — identical SHA-256 across two builds |
| G7.3 both FE specifications reported | **PASS** — 4 crops × 4 specifications |
| G8 ΔR² reported for every modelled crop | **PASS** — including the null results |
| G9 chronological split; skill reported at any sign | **PASS** — 3 of 4 crops negative |
| G10 F1–F4 exist; no dual axis; no jet/rainbow; greyscale-checked | **PASS** |
| G11 dashboard QA | **PASS** — 20 headless checks |
| G12 all 12 disclosures present | **PASS** — in README §6 and in the dashboard footer |
| G13 local commits clean; no push | **PASS** — no remote configured |
