# SRS — Telangana Kharif Rainfall–Yield Response Analysis

**Project ID:** `telangana-agromet`
**Version:** 1.0.0
**Status:** Approved for build (Tier 1)
**Owner:** *(candidate — B.Tech CSE)*

---

## 1. Purpose

Estimate the empirical relationship between kharif-season rainfall and crop yield
across Telangana districts, and locate the rainfall optimum (vertex) for each crop.

The analysis addresses a gap in agrometeorological advisory practice: advisories are
issued **forward in time** from forecasts. No systematic attempt is made to ask
**"has Telangana seen this season profile before, and what did yield do?"**

### 1.1 Research context

Bal et al. (2022), *Agricultural and Forest Meteorology* 313:108768 — "Assessing impact
of dry spells on the principal rainfed crops in major dryland regions of India" — reports
that a **Dry-Spell Index (DSI) explains yield loss better than SPI**, because SPI
captures only cumulative seasonal rainfall and ignores dry-spell duration.

**Direct consequence for this project:** a model using *seasonal rainfall total alone* is
reproducing the specific approach that source paper identifies as inferior. This project
must therefore test both and report the comparison.

---

## 2. Scope

### 2.1 In scope (Tier 1)

| # | Deliverable |
|---|---|
| S1 | Reproducible ERA5 daily weather ingest for Telangana district locations |
| S2 | Versioned, cached raw + processed datasets with a data manifest |
| S3 | Analysis panel joining weather to DES district yield statistics |
| S4 | Stage 1 model: district + year fixed-effects quadratic response curve |
| S5 | Stage 2 model: augmented feature set (dry-spell, heat) — R² comparison |
| S6 | Out-of-sample validation against a district-median baseline |
| S7 | Static publication figures (PNG) |
| S8 | Interactive map + infographic dashboard |
| S9 | README with limitations, provenance, and reproduction instructions |

### 2.2 Out of scope (explicitly deferred)

- Per-crop season windows (single common window used — see §5.2)
- Satellite NDVI / Sentinel-2 analysis
- Parent-district reconstruction of pre-2016 boundaries (see §4.3 — constraint identified)
- Rabi season analysis
- ~~Live 2026 yield forecasting~~ — **WITHDRAWN (ERRATA C10): a predicted-yield
  display is now in scope.** The 2026 figures are a model prediction, published
  per crop from that crop's own validated model, and every prediction carries its
  out-of-sample skill score.
- ~~Any prediction of yield for years not covered by DES observations~~ —
  **WITHDRAWN (ERRATA C10)**, on the same terms. Still prohibited: production
  totals as an independent claim, "%-chaining" from rainfall to yield, and any
  2026 figure for a crop whose model has no supported shape.

### 2.3 Non-negotiable constraints

| ID | Constraint |
|---|---|
| C1 | **No synthetic data.** Every numeric value traces to a cited source file. |
| C2 | **No fabricated results.** README reports measured numbers, including null results. |
| C3 | **No weather model output presented as measured data.** ERA5 is reanalysis — label it as such. |
| C4 | **Agent never pushes to remote.** Local commits only; owner controls all pushes. |
| C5 | **No threshold rule may be presented as a learned model.** |

---

## 3. Data sources

### 3.1 Yield (user-provided)

| Field | Value |
|---|---|
| Source | Directorate of Economics & Statistics (DES), Govt. of India — district-wise season-wise crop production statistics |
| Delivery | User-provided file, see §3.3 |
| Licence | Government open data, free for non-commercial use, attribution requested |
| Coverage | **2014-15 to 2022-23, Telangana region only** (AMENDED 2026-10-22, see plan/ERRATA.md C1 — the delivered file contains no seasons before 2014-15) |

### 3.2 Weather (pipeline-fetched)

| Field | Value |
|---|---|
| Source | Open-Meteo Historical Weather API |
| Dataset | **ERA5 reanalysis**, 0.25° (~25 km), 1940–present |
| Endpoint | `https://archive-api.open-meteo.com/v1/archive` |
| API key | **None required** |
| Licence | CC BY 4.0 — **attribution is mandatory** |
| Rate limit | 10,000 calls/day (free tier); this project requires ≈2 |
| Rate caveat | Endpoint exhibits intermittent `SSL_ERROR_SYSCALL`. **Retries are mandatory, not optional.** |

### 3.3 Input file

```
data/horizontal_crop_vertical_year_report.xls
```

**AMENDED (ERRATA C1, C2):** the delivered file parses as **(238, 111)** — 238
district-year rows and 36 crop groups x 3 metrics plus State/District/Year. It holds
**2014-15 to 2022-23** only; the earlier seasons assumed in §3.1 are not present.

**Format note:** despite the `.xls` extension, this file is an **HTML document** containing a
single `<table>`. It must be parsed with `pandas.read_html()`, not `read_excel()` with a
`.xls` engine.

---

## 4. District segmentation

### 4.1 Source of truth

**The DES file is authoritative.** District membership per year is derived from the data,
not from an external gazetteer. Where this SRS and the file disagree, the file wins and the
discrepancy is logged.

### 4.2 Observed structure (derived from the DES file — verified)

| Period | Districts | Event |
|---|---|---|
| 2014-15 → 2015-16 | 9 | Telangana formed; **district boundaries unchanged** |
| 2016-17 → 2017-18 | 30 | District reorganisation |
| 2018-19 → 2022-23 | 32 | Mulugu + Narayanpet appear |

**AMENDED (ERRATA C1):** the table above is what the delivered file actually contains.
The 2000-01 and 2001-02 → 2013-14 periods assumed in the original §4.2 are **not in
the file** and have been removed. Counts were re-derived from the data, not assumed.

**Unique district values across the whole file: 32** (no Hyderabad row exists in the
delivered file; the boundary GeoJSON carries Hyderabad as an explicit no-data feature).

### 4.3 Zero-sum partition — KNOWN CONSTRAINT

The requirement is a **zero-sum (disjoint, gapless) partition** of the state into parent
districts, such that:

```
Σ yield_parent(year) = Σ [production_child(year)] / Σ [area_child(year)]   across all children
```

for any parent year.

**⚠ This is a hard blocker that must be verified before implementation.**

The April 2016 reorganisation is **not known to be a clean partition**. At least one new
district appears to draw territory from **two** parents (Suryapet is widely reported as
formed from parts of both Khammam and Nalgonda; Vikarabad and Narayanpet have
similarly mixed origins). Where a child spans two parents, **no exact zero-sum partition
of parents into children exists.**

**Required action:** the implementing agent MUST resolve this before any parent aggregation
is written. See GUIDE.md Step 2.

**RESOLVED (ERRATA C4):** a district division is **zero-sum** — when an undivided
district *x* was divided into *y* and *z* in 2016, *x = y + z*, so a parent-level
figure for a post-2016 season is `sum(production_children) / sum(area_children)`.
The children take the parent's name or a new one, and the dataset reports them
individually. The reconstruction is **not attempted** — Suryapet was formed from parts
of two parents (Khammam and Nalgonda), so those parents cannot be rebuilt from the
children the dataset names, and it is unnecessary because era-tagged fixed effects
keep pre- and post-2016 districts apart. An area-based check of the zero-sum property
was attempted and was inconclusive (residuals +65 % to −70 %, swamped by crop choice),
so the zero-sum status is taken as a fact of the reorganisation rather than a
measurement. Full reasoning: `data/geo/PARTITION_NOTE.md`. Tier 1 proceeds with
era-tagged district ids.

**Interim design that sidesteps the constraint:** treat pre-2016 and post-2016 as
**distinct district entities** (era-tagged IDs, §4.4). This requires no partition, no
gazetteer lookup, and makes no continuity assumption. **This is the Tier 1 default.**

### 4.4 District ID convention

```
{slug}__pre2016    e.g.  adilabad__pre2016      (2014-15 … 2015-16)
{slug}__post2016   e.g.  adilabad__post2016     (2016-17 … 2022-23)
```

District slugs are derived from the DES `District` column by stripping the leading index
prefix (`"1. Adilabad"` → `adilabad`) and lowercasing.

**This convention is mandatory.** It makes the pre/post-2016 discontinuity explicit in the
data rather than silently mixing incompatible geographic units.

### 4.5 Primary vs. extended panel

| Panel | Definition | Use |
|---|---|---|
| **Primary** | 2016-17 → 2022-23, post-2016 districts only | All reported results |
| **Extended** | 2014-15 → 2022-23, both eras, era-tagged | Robustness check only |

**AMENDED (ERRATA C1):** the extended panel is **2014-15 → 2022-23** — the earliest
seasons the delivered file contains. Its pre-2016 block is 2014-15 and 2015-16 only
(9 old-boundary districts).

The extended panel is reported **only** as a stability check on the estimated vertex. It is
never the headline.

---

## 5. Analysis specification

### 5.1 Season definition

Telangana District Collectorate (Kamareddy), official definition:

> *"The agricultural year (June to May) is divided into two seasons... All crops sown
> during the period from **June to September** are recorded as **Kharif (Vanakalam)**. All
> crops sown during **October to March** are considered **Rabi (Yasangi)**."*

**Analysis window: 1 June – 30 September** (official Kharif classification window).

**Ingest window: 1 June – 31 October.** Wider than the analysis window so that late-season
rainfall (cotton and arhar run to Nov–Dec) is captured in the dry-spell and heat features.

**AMENDED (ERRATA C1):** the weather ingest window is **2014-06-01 → 2023-10-31**,
matching the seasons the delivered file actually covers. The 2026 marker window
(2026-06-01 → 2026-09-30) is fetched separately and labelled.

**Mandatory limitation text:** this is the *sowing* window, not the full growing season.
Cotton sown in June grows to December, so Jun–Sep rainfall undercounts late-season
contribution for cotton and arhar.

### 5.2 Single common window — rationale

A single common window is used for **all crops**. Crop-specific windows would place each
crop's rainfall on a different scale, making cross-crop comparison of the estimated vertex
invalid. Cross-crop comparability is worth more than marginal per-crop accuracy at Tier 1.

### 5.3 Crops

| Crop | Unit | Tier | Basis |
|---|---|---|---|
| Cotton (lint) | **bales/ha** | **Primary** | Telangana Dept. of Agriculture lists cotton among "sowings of rainfed crops" |
| Arhar/Tur | t/ha | **Primary** | Rainfed pulse |
| Moong (Green Gram) | t/ha | **Primary** | Rainfed pulse |
| Rice (kharif) | t/ha | **Secondary** | Telangana Dept. of Agriculture lists paddy under "assured irrigation sources" |

**AMENDED (ERRATA C3, amended v1.1.0):** the delivered file carries **36 kharif crop groups**
(all labelled Kharif; no Rabi groups). **Two are reported in bales**, not tonnes:
`Cotton(lint)` and `Mesta`. **The project scope was narrowed by the owner to four
crops** (Cotton lint, Arhar/Tur, Moong, Rice); the remaining 32 groups are removed
during ingest as unnecessary columns and rows and are **not** carried in the panel or
the dashboard. The dropped groups and the reasons are listed in
`data/processed/crops_kharif_clean.metadata.json`.

**⚠ Unit hazard — mandatory.** Cotton is reported in **bales**, not tonnes. Its column is
`Cotton(lint)__Kharif__Yield (Bales/Hectare)`, **not** `Yield (Tonne/Hectare)`. Any
column-selection code that assumes the tonne suffix will silently drop cotton entirely.

**Expected finding, to be tested not assumed:** irrigation-buffered rice should show a
**weaker** rainfall response than the rainfed crops. A flat rice curve is a *result* (it
evidences irrigation buffering), not a failure — but only if it was framed in advance.

### 5.4 Model specification

**Stage 1 — Response curve (headline).**

```
yield_{i,c,t} = β₁ · R_{i,t} + β₂ · R²_{i,t} + α_i (district FE) + γ_t (year FE) + ε
```

- Estimator: OLS
- R = seasonal rainfall total (mm), 1 Jun – 30 Sep
- **Vertex (optimum rainfall):** `R* = −β₁ / (2·β₂)`
- Report R*, the deficit-limb slope, the excess-limb slope, R², and N

**Stage 2 — Augmented features.**

Add to the same specification: longest dry run (days, rain < 2.5 mm/day), count of days
in runs ≥ 5 days, heat days (Tmax > 35 °C), mean daily VPD max, rainy-day count.

**Mandatory comparison:** report ΔR² (Stage 2 − Stage 1). This is the test of Bal et al.'s
central claim on open data for Telangana.

- ΔR² materially positive → dry-spell duration adds explanatory power beyond cumulative
  rainfall. **This is the project's principal contribution.**
- ΔR² ≈ 0 → cumulative rainfall is sufficient. Also a legitimate, reportable result.

**Either outcome is a valid deliverable.** Neither may be suppressed or reframed.

### 5.5 Validation

| Item | Specification |
|---|---|
| Split | **Chronological.** Train ≤ 2019-20, test ≥ 2020-21. **Never random — random splits leak across autocorrelated weather years.** |
| Baseline | District-crop 10-year median yield (computed on train period only) |
| Metric | Out-of-sample RMSE and MAE vs. baseline; skill score = 1 − RMSE_model/RMSE_baseline |
| Leakage guard | Baseline statistics, standardisation, and any imputation fit **on train only** |

### 5.6 2026 handling — MANDATORY

2026 yield observations **do not exist** in the DES data (the series ends at
2022-23). The 2026 figures are therefore **model predictions**, and this
section governs how they are produced, labelled and bounded.

**Permitted:**
- 2026 *observed* rainfall from ERA5, as the input to the 2026 prediction
- A 2026 prediction per crop, from that crop's own model, with its out-of-sample
  skill score printed beside it
- A dashed, visually separated 2026 segment, with the extrapolation gap explicit

**Prohibited:**
- A 2026 figure for a crop whose selected specification returns a non-positive
  yield at any district's observed 2026 rainfall
- Any language implying the 2026 prediction has been validated against a 2026
  outcome
- Production totals as an independent claim: the 2026 total is the prediction
  rescaled by area, and the area is an assumption
- Any prediction interval — with three holdout seasons there is not enough data
  to calibrate one honestly

**Required labelling wherever 2026 appears:**
> "2026 is a model prediction, not an observation and not a validated forecast. Each
> crop is forecast by its own specification, selected by leave-one-season-out
> cross-validation inside the fitting period; the out-of-sample skill of that
> specification is printed beside every prediction."

**Model selection (ERRATA C10.2).** One specification per crop, chosen by
leave-one-season-out cross-validation **inside the fitting period only**; the
holdout block is evaluated once afterwards, so the reported skill is a holdout
statistic and not a selection statistic.

**Measure and aggregation (ERRATA C10.3, C10.4).**
- The measure is **yield per hectare**. A production total mixes productivity
  with land utilisation and is not a yield.
- State figures are **area-weighted**: `SUM(area × yield) ÷ SUM(area)`. The
  unweighted mean of district yields is not used anywhere.
- The 2026 area baseline is each district's **2022-23 kharif area**, applied
  identically to the prediction and to the Telangana average, and stated
  wherever the 2026 total appears.

**The 2026 layer on the map (ERRATA C12).** 2026 may be shown as a season on
the map, labelled `2026-27 (prediction)`. Every value under it is a model
prediction, and the map note, the hover card and the season readout must say
so. The layer has its own fixed colour domain per crop — the predictions
occupy the middle of the observed range — and the legend caption must state
which domain is in force. The season readout may carry the 2026 point, drawn
**dashed**, on the same convention as the forecast chart.

**The state summary (ERRATA C12.4).** A five-row summary — the four crops and
the kharif rainfall, each against the Telangana average — may sit above the
district table. The crop name is the parent header; 2026 and the state
average are the two columns under it. The change rides in the 2026 cell, with
the sign always printed. Totals are in millions.

**Display (ERRATA C11).** The 2026 prediction is drawn on a **categorical**
time axis — the nine observed seasons, then 2026 as its own final step — with
the 2026 segment **dashed**, because a continuous axis would place 2026 to the
left of the record and read as "before 2014". Where crops measured in
different units share one axis, the axis is **indexed** to each crop's own
Telangana average, and the index base is stated where the chart is.

---

## 6. Storage & versioning

### 6.1 Layout

```
telangana-agromet/
├── data/
│   ├── raw/                      # IMMUTABLE. Never edited, never deleted.
│   │   ├── des/                  # user-supplied yield file + checksum
│   │   └── openmeteo/            # raw API JSON, one file per fetch
│   ├── interim/
│   │   └── weather_daily.parquet
│   ├── processed/
│   │   ├── panel_v1.0.0.parquet
│   │   └── models_v1.0.0.joblib
│   ├── geo/
│   │   └── districts.geojson
│   └── manifests/
│       ├── fetch_manifest.json
│       └── checksums.sha256
├── src/
├── figures/                      # static PNG outputs
├── dashboard/                    # GitHub Pages site
└── DATA_VERSION                  # "1.0.0"
```

### 6.2 Versioning rules

| Rule | Detail |
|---|---|
| Raw is immutable | `data/raw/**` is append-only. Corrections → new file, never overwrite. |
| Semantic versions | `MAJOR.MINOR.PATCH` on processed artifacts |
| MAJOR | schema change (column added/removed/renamed) |
| MINOR | new rows or years added; no schema change |
| PATCH | backfill, bug fix, no row/schema change |
| Manifest | every fetch records: source URL, params, fetch UTC timestamp, SHA-256, row count |
| Reproducibility | given the same `DATA_VERSION` + manifest, the panel must rebuild byte-identical |

### 6.3 Mandatory data manifest fields

```json
{
  "artifact": "panel_v1.0.0.parquet",
  "created_utc": "ISO-8601",
  "weather_source": "open-meteo/era5",
  "weather_endpoint": "https://archive-api.open-meteo.com/v1/archive",
  "yield_source": "DES district-wise season-wise crop production",
  "yield_file_sha256": "...",
  "temp_window": ["2014-06-01", "2023-10-31"],
  "analysis_window": ["06-01", "09-30"],
  "districts": 32,
  "crops": ["Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)", "Rice"],
  "rows": 0,
  "sha256": "..."
}
```

---

## 7. Visualisation specification

### 7.1 Colour system — domain-standard, colourblind-safe

**Red/green pairing is prohibited.** ~8% of men have red-green colour vision deficiency;
this audience includes statisticians who will check.

| Semantic | Colormap | Type | Rationale |
|---|---|---|---|
| **Rainfall deficit / drought severity** | `YlOrRd` | Sequential | Standard climate-drought convention. Light = wet, dark red = severe deficit. |
| **Yield anomaly (%)** | `RdYlBu` | Diverging | Blue = below normal, cream = normal, red = above normal. Perceptually uniform, colourblind-safe. Zero must map to the neutral midpoint. **AMENDED (ERRATA C7):** matplotlib's `RdYlBu` runs red→blue as the value rises, so the ramp is used reversed (`RdYlBu_r`) to deliver the semantics this table fixes. The colormap itself is unchanged, and the legend names the direction explicitly.** |
| **Crop identity** | Okabe-Ito (fixed) | Fixed | One colour per crop, **identical in every chart, figure and selector**. A crop's colour never changes when the user switches views. |
| **Response-curve scatter/line** | `#1f77b4` + `#d62728` | Fixed | Matplotlib tab colours; maximum contrast on white |
| **Rainfall bars** | `#4C78A8` | Fixed | — |
| **Yield lines** | `#E45756` | Fixed | — |
| **2026 marker** | `#111111` dashed | Fixed | Maximum salience, unambiguous against all series |

**Crop identity palette (Okabe-Ito, colourblind-safe):**

| Crop | Hex | Basis |
|---|---|---|
| Rice | `#009E73` | paddy green |
| Arhar/Tur | `#D55E00` | tur dal vermillion |
| Moong | `#CCBB44` | green gram yellow-green |
| Cotton | `#0072B2` | boll blue |

**Rules:**
- A crop's colour is **fixed**: the same crop carries the same hex in the
  response curves, the time series, the table and the selector chips. Switching
  crops must never repaint the other crops.
- Red/green pairings are prohibited **between two data series**. Okabe-Ito's
  green (`#009E73`) and vermillion (`#D55E00`) are distinguishable under
  deuteranopia and protanopia, which is the property that matters; the two are
  never the only thing distinguishing two adjacent series, and every series
  also carries a label.
- Sequential ramps → monotonically increasing perceived lightness. Never a rainbow/jet map.
- Diverging ramps → **zero always maps to the exact midpoint colour**, never to ramp index 0.
- Domain **must** be fixed per metric. Do **not** auto-rescale between views.
- Every map/figure carries a **legend with numeric units** and the colormap name in the caption.
- Never encode meaning by colour alone — pair with a value label, pattern, or icon.

### 7.2 Icons

Font Awesome 6 (CDN) or equivalent open icon set. Mandated semantic mapping:

| Concept | Icon |
|---|---|
| Rainfall | `fa-cloud-rain` |
| Crop yield | `fa-wheat-awn` |
| Dry spell / drought risk | `fa-triangle-exclamation` |
| Heat stress | `fa-temperature-high` |
| District boundary | `fa-map-location-dot` |
| Advisory | `fa-comment-dots` |
| Model / analysis | `fa-chart-line` |

Icons supplement colour and text. They do not replace either.

### 7.3 Static figures (Tier 1 deliverables — these are what the email carries)

| ID | Figure | Content |
|---|---|---|
| F1 | **Response curve (HEADLINE)** | Scatter: seasonal rainfall (x) vs yield (y), one panel per primary crop. Fitted quadratic, **vertex marked and annotated**, 2026 rainfall as dashed vertical marker. Stage 1 and Stage 2 side by side. |
| F2 | Time series, stacked | Top: rainfall (mm) + p10–p90 band. Bottom: yield (t/ha). Shared x-axis. **No dual axis.** |
| F3 | Validation | Model vs. baseline RMSE by crop; chronological test period |
| F4 | Choropleth | Yield anomaly (%) by district, `RdYlBu`, 2018-19 onward only |

### 7.4 Dashboard (Tier 2 — bonus, never blocks delivery)

- **Library:** Leaflet (CDN) for the map. D3 or Chart.js for charts. Static site — no server.
- **Layout:**

```
┌───────────────────────────────────────────────────────────┐
│ [Crop ▾] [Year ▾] [Metric ▾]  | Kharif · Telangana · ERA5 │
├────────────────────────┬──────────────────────────────────┤
│  Leaflet choropleth    │  Rainfall (mm) ▁▂▅█▇▃▁▂▅█▇▃▁▂     │
│  32 districts          ├──────────────────────────────────┤
│  yield anomaly (%)     │  Yield (t/ha)  ▁▃▆█▇▂▁▃▆█▇▂▁      │
│  RdYlBu, fixed domain  │        + p10–p90 band            │
├────────────────────────┴──────────────────────────────────┤
│  Response curve · per crop · vertex ● · 2026 marker ▼      │
└───────────────────────────────────────────────────────────┘
```

- **Map metric:** yield **anomaly (%)** by default, not absolute yield. Absolute yield across
  Telangana is dominated by soil and irrigation and would render a soil map, not a
  risk map. Offer absolute as a secondary toggle with the caveat displayed.
- **Post-2016 districts only** on the map.
- District boundaries: 32-district Telangana GeoJSON. **Source URL must be recorded in the
  manifest.** All three candidate URLs previously tried returned 404.
  **AMENDED (ERRATA C5): a working source was found and is recorded with its SHA-256 —
  `https://raw.githubusercontent.com/gpavanb1/Telangana-Visualisation/master/data/Telangana.geojson`
  (33 features: 32 used, Hyderabad carried as no-data). 13 DES district names differ
  from the boundary file's spelling and are joined through `data/geo/name_crosswalk.csv`.**

### 7.5 Accessibility

- Minimum text/background contrast 4.5:1
- Colormap legends labelled with units and colormap name
- All figures readable in greyscale (test before delivery)
- Alt text on dashboard panels

---

## 8. Reproducibility & repository

| Requirement | Detail |
|---|---|
| Language | Python 3.11+ |
| Environment | `uv` or `venv`; pinned lockfile committed |
| Non-negotiable deps | `pandas`, `numpy`, `pyarrow`, `scipy`, `statsmodels`, `scikit-learn`, `matplotlib`, `folium`/`leaflet` |
| Determinism | All stochastic steps explicitly seeded; seed recorded in manifest |
| Seeding | `PYTHONHASHSEED=0`, fixed `random_state` in every estimator |

### 8.1 Git policy — MANDATORY

| Rule | Detail |
|---|---|
| **Agent may** | `git add`, `git commit`, `git status`, `git diff`, `git log`, `git branch` |
| **Agent may NOT** | `git push`, `git remote add`, `git remote -v` with credentials, force any operation, create tags on the owner's behalf |
| **Owner-only** | All pushes, all remotes, all releases, all tags |
| Branch | Work on `main`. Never commit directly to a protected default branch without owner's explicit instruction. |
| Commit format | Conventional Commits: `feat:`, `fix:`, `data:`, `docs:`, `chore:`, `refactor:` |
| Commit scope | One logical change per commit. Never `git add -A` on a tree containing unrelated experiments. |
| Large data | `data/raw/` and `data/processed/` are **gitignored** (parquet/JSON blobs). Commit **manifests, checksums and DATA_VERSION** instead — this is how reproducibility survives without bloating the repo. |
| Secrets | No credentials, API keys, or `.env` files. This project needs none. |

---

## 9. Mandatory disclosures

These must appear verbatim in README and in any derived document. They are not optional.

1. **Reanalysis, not observation.** ERA5 is a model-assimilated reanalysis product at 0.25°
   (~25 km) resolution. It is not IMD station gauge data.
2. **Convective rainfall bias.** ERA5 is known to underestimate convective rainfall over
   dryland interiors. Absolute rainfall totals in this analysis may be biased low.
3. **No irrigation, soil, or input data.** This is the dominant confound. Reported effects
   are rainfall's marginal association **conditional on all other factors being average**,
   not a causal yield model.
4. **District aggregates, not farm-level.**
5. **Boundary discontinuity.** District boundaries were revised in 2016 and 2018. Pre- and
   post-revision periods are modelled as distinct fixed-effect groups, **not** as a
   continuous panel.
6. **Sowing window ≠ season.** Jun–Sep is the official Kharif sowing window; cotton and
   arhar grow to Nov–Dec, so late-season rainfall is undercounted.
7. **DES agency discontinuity.** Pre-2014 figures originate with undivided Andhra Pradesh
   DES; post-2014 with Telangana DES. Estimation methodology may differ.
8. **Cotton is reported in bales**, not tonnes, and is modelled on that scale.
9. **Small sample per crop.** ~220 district-year observations per crop in the primary
   panel. *(Verified against the delivered file: Cotton 220, Rice 220, Arhar/Tur 219,
   Moong 209.)*
10. **2026 is a model prediction, not a validated forecast.** See §5.6.
11. **2026 planted area does not exist.** The state-level 2026 figures are
    area-weighted on each district's 2022-23 kharif area, applied identically
    to the prediction and to the Telangana average. The 2026 total is the
    prediction rescaled by that area, not an independent claim.
12. **Attribution.** ERA5 via Open-Meteo — CC BY 4.0. DES — Govt. of India open data.
13. **Rule-based percentile bands** are descriptive, not inferential. No confidence intervals
    are claimed.

---

## 10. Acceptance criteria

The build is complete when **all** of the following are true.

| # | Criterion | Verification |
|---|---|---|
| A1 | Every number in README traces to a committed artefact | Spot-check 5 values against `data/processed/` |
| A2 | `data/raw/` contains the unmodified source responses | Checksums match manifest |
| A3 | Processed panel rebuilds identically from raw | Re-run; compare SHA-256 |
| A4 | Cotton present and in **bales** | Panel row count for Cotton > 0 |
| A5 | Stage 1 vertex reported for all 3 primary crops | README §Results |
| A6 | Stage 2 ΔR² reported, even if ≈ 0 | README §Results |
| A7 | Out-of-sample skill vs. median baseline reported | F3 |
| A8 | Random train/test split absent from codebase | grep |
| A9 | F1 exists with vertex annotated | File present, inspected |
| A10 | No dual-axis plot anywhere | grep for `twinx` |
| A11 | Colormaps are `YlOrRd` / `RdYlBu`; no jet/rainbow | grep for `jet\|rainbow` |
| A12 | All 12 disclosures present in README | Checklist |
| A13 | Local commits exist; **zero remote operations performed** | `git log --oneline`, no push in reflog |
| A14 | `random_state` set in every estimator | grep |
| A15 | `.gitignore` excludes data blobs | `git status` clean |

---

## 11. Tier 2 backlog (not required for delivery)

- Parent-district reconstruction — **blocked on §4.3 constraint**
- ERA5-Land sensitivity check (0.1°)
- Crop-specific season windows
- Per-district response curves (requires ≥20 yr/district; current data insufficient)
- Satellite NDVI layer
- Additional DES years (2023-24 onward) if published

---

## 12. Out of scope for this document

No email text, no recipient selection, and no selection-process strategy are specified here.
Those are separate deliverables governed by different constraints.