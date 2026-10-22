# GUIDE.md — Build Harness for `telangana-agromet`

**Audience:** an autonomous coding agent with no prior context on this project.
**Authority:** `SRS.md` is the contract. This file is the execution procedure.
**If they conflict, SRS.md wins.**

---

## 0. Hard rules — read before anything else

1. **The agent MUST NOT run `git push`** under any circumstance. Not once, not "just to
   test," not if asked in a log message. Local commits only. The owner pushes.
2. **No synthetic data.** No `np.random`, no `simulate`, no hardcoded weather, no invented
   district values. If a number is not traceable to a source file, it does not go in.
3. **Do not fabricate a result.** A null result is reported as a null result.
4. **Every step has a gate.** If the gate fails, fix it before proceeding. Do not proceed
   and note it for later.
5. **Raw data is immutable.** Never edit, move, or delete anything under `data/raw/`.
6. **Stop and report** on any `STOP` condition. Do not improvise past a hard blocker.

---

## 1. Environment setup

### Step 1.1 — Project skeleton

```bash
cd /workspace/telangana-agromet
mkdir -p data/{raw/{des,openmeteo},interim,processed,geo,manifests} \
         src figures dashboard assets
```

**Gate:** all directories exist.

### Step 1.2 — Python environment

```bash
python3 --version                    # require >= 3.11
uv venv --python 3.11 .venv          # fallback: python3 -m venv .venv
uv pip install pandas numpy pyarrow scipy statsmodels scikit-learn matplotlib requests
```

**Gate:** `python -c "import pandas,numpy,pyarrow,scipy,statsmodels,sklearn,matplotlib"`

### Step 1.3 — `.gitignore` — write BEFORE first commit

```gitignore
.venv/
__pycache__/
*.pyc
.ipynb_checkpoints/

# data blobs — reproducibility is carried by manifests, not by committing blobs
data/raw/**
data/interim/**
data/processed/**
!data/manifests/

# secrets — this project needs none; the rule exists to stop them appearing
.env
*.key
*.pem
```

**Gate:** `git status --porcelain` shows no data files staged.

### Step 1.4 — Determinism

Every Python invocation in this project runs with:

```bash
PYTHONHASHSEED=0 python src/<script>.py
```

**Gate:** documented in README.

---

## 2. District segmentation — **BLOCKING STEP**

> SRS §4.3 records an unresolved constraint: the 2016 reorganisation may **not** be a clean
> partition. Resolve this before writing any aggregation code.

### Step 2.1 — Extract district membership from the DES file

Derive, empirically, which districts appear in which years. The SRS §4.2 table is the
expected result — **verify it, do not assume it.**

```python
import pandas as pd, re
df = pd.read_html(SRC)[0]
df.columns = ["__".join(str(c) for c in col if not str(c).startswith("Unnamed"))
              for col in df.columns]
Y = [c for c in df.columns if c.endswith("Year")][0]
D = [c for c in df.columns if c.endswith("District")][0]
df["Year"], df["District"] = df[Y].str.strip(), df[D].str.strip()
slugs = df["District"].str.replace(r"^\d+\.\s*", "", regex=True).str.lower()
```

Output the district × year membership matrix.

**Gate G2.1:** the period-by-period district counts match SRS §4.2
(10 / 9 / 9 / 30 / 32). **If they do not match, STOP and report the discrepancy.** Do not
rewrite the SRS silently.

### Step 2.2 — Build the era-tagged district dimension

Create `data/geo/districts.csv`:

```
district_slug, district_label, era, first_year, last_year, lat, lon, source
adilabad,        Adilabad,  pre2016,  2014-15, 2015-16, <lat>, <lon>, HQFILL
adilabad,        Adilabad,  post2016, 2016-17, 2022-23, <lat>, <lon>, CENTROID
```

**Era rule (SRS §4.4):** `pre2016` covers 2014-15 … 2015-16. `post2016` covers
2016-17 … 2022-23. The delivered file starts at 2014-15 (ERRATA C1), so the
pre-2016 block is two seasons, not the 2001-02 … 2013-14 block the original
plan assumed. Hyderabad 2000-01 is not present in the delivered file at all.

**Gate G2.2:** no `district_slug` appears under both eras as a single entity. Every row
carries exactly one era tag.

### Step 2.3 — Resolve the partition constraint — **HARD GATE**

Attempt to determine whether the 2016 reorganisation admits an exact zero-sum
parent → child partition.

```bash
# Investigate and record the finding. Sources to consult:
#   - April 2016 Gazette of India notification (Telangana district reorganisation)
#   - Telangana Open Data portal  (data.telangana.gov.in)
#   - dataful.in district metadata (carries LGD codes + parent references)
```

**Three possible outcomes:**

| Finding | Action |
|---|---|
| **Clean partition exists** | Record the mapping to `data/geo/parent_child_map.csv`. Tier 2 becomes possible. |
| **Not a clean partition** (at least one child spans two parents) | Record the conflict. **Tier 2 is BLOCKED.** Proceed with era-tagged IDs only. |
| **Cannot be determined from available sources** | Record as unresolved. **Tier 2 is BLOCKED.** Proceed with era-tagged IDs only. |

Write the finding to `data/geo/PARTITION_NOTE.md` with the sources consulted and a one-line
verdict.

**Gate G2.3 (hard):** `PARTITION_NOTE.md` exists and states one of the three verdicts
explicitly. **Tier 1 continues in all three cases.** Do not attempt parent aggregation in
Tier 1 under any outcome.

### Step 2.4 — District coordinates

**Required:** lat/lon per district-era.

**Preferred method:** area-weighted centroid of the ERA5 0.25° grid cells intersecting the
district polygon. This requires a boundary file and correctly handles large districts
(e.g. KB Asifabad) whose headquarters are far from their centroid.

**Fallback if boundaries are unavailable:** district headquarters coordinates.

**Either way, `data/manifests/` MUST record which method was used, the source URL, and the
fetch date.** An unrecorded coordinate source is a reproducibility failure.

**Gate G2.4:** all districts in the primary panel have non-null lat/lon; the method is
recorded in the manifest.

### Step 2.5 — District boundaries for the map

Source a **32-district Telangana GeoJSON**. Three previously attempted URLs returned 404:

```
https://raw.githubusercontent.com/geohacker/telangana/master/district/telangana_district.geojson          → 404
https://raw.githubusercontent.com/india-ai/india-maps-data/main/geojson/telangana_districts.geojson      → 404
https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.geojson             → 404
```

Try `data.telangana.gov.in`, `github.com/datameet/maps`, and a GitHub code search.

**Gate G2.5:** `data/geo/districts.geojson` exists, contains ≥32 features, and its district
names join to `districts.csv` at ≥95%.

> **This gates only the map (Tier 2) and the centroid method. If boundaries cannot be
> sourced, use HQ coordinates and proceed — the analysis does not depend on it.**

---

## 3. Yield data ingest

### Step 3.1 — Copy and checksum the input

```bash
cp data/horizontal_crop_vertical_year_report.xls \
   data/raw/des/horizontal_crop_vertical_year_report.xls
shasum -a 256 data/raw/des/*.xls | tee data/manifests/checksums.sha256
```

*(The source path in the original guide assumed a `/workspace/attachments/...` mount; the
delivered file lives in `data/`. The copy into `data/raw/des/` and its checksum are
unchanged in intent: the raw copy is immutable.)*

**Gate G3.1:** checksum recorded. `data/raw/des/` is now immutable.

### Step 3.2 — Parse (read_html, NOT read_excel)

```python
# SRS §3.3: this file is HTML despite the .xls extension.
raw = pd.read_html("data/raw/des/horizontal_crop_vertical_year_report.xls")[0]
```

Using `read_excel` with an `.xls` engine will fail or silently misparse.

**Gate G3.2:** shape is `(238, 111)`. **AMENDED (ERRATA C2)** — the original
`(365, 126)` assumed 2000-01 … 2022-23 and a wider column set; the delivered file
parses as 238 district-year rows x (State + District + Year + 36 crop groups x 3
metrics). `pandas.read_html` expands the rowspans, so State and District arrive
populated.

### Step 3.3 — Reshape wide → long

Columns are 3-level MultiIndex: `(crop, season, metric)`. Melt to one row per
**district × year × crop**.

**⚠ Cotton unit hazard (SRS §5.3):** cotton's yield column is
`Cotton(lint)__Kharif__Yield (Bales/Hectare)`. It does **not** carry the `Tonne` suffix.
Any filter like `"Tonne" in col` will drop cotton silently.

Emit a `unit` column per crop. Never assume tonnes.

**Gate G3.3:** a per-crop row-count table is printed and matches the expected magnitudes
(Rice ≈ 365, Cotton ≈ 364, Arhar/Tur ≈ 364, Maize ≈ 364, Moong ≈ 359, with **zero**
NaN-padded rows). Cotton's unit reads `bales/ha`.

### Step 3.4 — Quality filter

| Rule | Action |
|---|---|
| `area == 0` | drop |
| `production == 0` | drop |
| `area < 10 ha` | drop (matches DES convention for non-commercial plots) |
| `yield` missing | drop |
| District not in primary panel | keep in raw, exclude at panel build |

Record the drop count per crop in the manifest.

**Gate G3.4:** drop counts are non-zero and explained.

---

## 4. Weather ingest

### Step 4.1 — Endpoint and retry harness — **MANDATORY**

```python
# archive-api.open-meteo.com returns intermittent SSL_ERROR_SYSCALL (~50% observed).
# Retries are required, not defensive overkill.
def fetch(url, tries=8):
    for attempt in range(tries):
        proc = subprocess.run(["curl", "-sS", "-m", "60", "-w", "\n%{http_code}", url],
                              capture_output=True, text=True)
        body, _, code = proc.stdout.rpartition("\n")
        if code == "200" and body.strip():
            return json.loads(body)
        time.sleep(2 * (attempt + 1))          # HTTP 000: network drop, retry immediately
        # HTTP 429 would require a LONG shared cooldown, not an immediate retry loop
    raise RuntimeError(f"exhausted {tries} attempts: {url[:80]}")
```

**Never use `urllib`** — it fails through this network path on nearly every request while
`curl` succeeds.

**Quota (added during the build, ERRATA C6).** The free tier also enforces an *hourly*
request quota and answers `429 {"reason": "Hourly API request limit exceeded. Please try
again in the next hour."}`. A generic 429 gets a 60 s cooldown; the hourly-quota error
waits for the top of the next hour. The 2026 marker window is fetched in a single
multi-coordinate request to keep the call count down. The API also resolves a request to
the surrounding ERA5 grid node rather than echoing the requested coordinate, so the
block-count check is paired with a half-cell (0.15 deg) coordinate tolerance and the
observed deviation is recorded per fetch in the manifest.

**Gate G4.1:** a single fetch succeeds within the retry budget.

### Step 4.2 — Ingest window

```
start_date = 2001-06-01
end_date   = 2023-10-31
```

Wider than the Jun–Sep analysis window (SRS §5.1) so late-season rainfall is captured.

**Gate G4.2:** returned date range is contiguous with no internal gaps.

### Step 4.3 — Daily variables

```
daily=precipitation_sum,temperature_2m_max,temperature_2m_min,
      vapour_pressure_deficit_max,shortwave_radiation_sum
```

All five are confirmed available as daily aggregations in the ERA5 schema.

### Step 4.4 — Batch by multi-coordinate request

Open-Meteo accepts comma-separated coordinates in a single call, returning one array per
coordinate. One request covers all districts.

**Gate G4.4:** the number of returned coordinate blocks equals the number of requested
districts. **If it does not match, do not proceed** — a silent mismatch misaligns every
weather row with its district.

### Step 4.5 — Cache raw, then transform

Write each response to `data/raw/openmeteo/<era5>_<hash>.json` **before** any processing.
Then build `data/interim/weather_daily.parquet` with one row per
`district_slug × date`.

**Gate G4.5:** row count = Σ(districts × days in window). NaN rate reported.

---

## 5. Feature engineering

### Step 5.1 — Season window

Filter to **1 June – 30 September** for all rainfall/curve features (SRS §5.1).
Keep the full Jun–Oct ingest for dry-spell features.

### Step 5.2 — Required features

| Feature | Derivation |
|---|---|
| `rain_mm` | Σ `precipitation_sum`, Jun 1 – Sep 30 |
| `rain_days` | count days with `precipitation_sum` ≥ 2.5 mm |
| `dry_run_max` | longest consecutive days with `precipitation_sum` < 2.5 mm |
| `dry_days_ge5` | days inside runs ≥ 5 days |
| `heat_days` | count days with `temperature_2m_max` > 35 °C |
| `vpd_mean` | mean `vapour_pressure_deficit_max` |
| `tmax_mean` | mean `temperature_2m_max` |

**The 2.5 mm threshold is the standard WMO "rain day" definition.** Cite it in the README.

### Step 5.3 — Strict causality

Dry-run features must be computed from data **up to and including** day *t*. Never use a
trailing window that peeks forward. When a feature is used to predict a period target, the
window must close before the target opens.

**Gate G5.3:** write an explicit assertion or comment at each rolling/shifting operation
stating which direction the window looks. The reviewer will check this.

---

## 6. Panel construction

### Step 6.1 — Join

`district_slug` (with era) × `year` × `crop` ← DES yield + ERA5 features.

**Note (SRS §5.4 / §6.2):** rainfall is at district-year level but yield is at
district-year-crop level. Rainfall therefore repeats across crops. The **effective**
independent sample for a single-crop model is the district-year count, **not**
district-year × crops. State this in the README.

### Step 6.2 — Target construction

```
yield_anom_pct = 100 × (yield / median_yield_for_that_district_crop_panel) − 1
```

Median computed **on the training period only** (SRS §5.5 leakage guard).

**Stage 1 uses raw yield** — the vertex is only interpretable on the raw scale.
Anomaly is a reporting/secondary view, not the Stage 1 target.

### Step 6.3 — Dataset versioning

Write `data/processed/panel_v1.0.0.parquet`, update `DATA_VERSION` to `1.0.0`, and emit
`data/manifests/fetch_manifest.json` per SRS §6.3.

**Gate G6.3:** rebuild from raw produces an identical SHA-256.

---

## 7. Stage 1 — Response curve

### Step 7.1 — Specification

```
yield ~ rain_mm + rain_mm² + C(district_era) + C(year)
```

Statsmodels OLS. `.fit()` — inspect the summary.

### Step 7.2 — Vertex

```
R* = −β₁ / (2·β₂)
```

**Report R\* only if β₂ < 0 and is significant at p < 0.05.** If β₂ ≥ 0 there is no
inverted-U — a monotonic or flat relationship. Report that honestly; it is a valid result
and **must not be reframed** as a vertex.

### Step 7.3 — Robustness to year FE

Refit **without** year fixed effects. Report both vertices.

| Outcome | Interpretation |
|---|---|
| Both stable | Strong result — report the range |
| Divergent | Year FE specification is primary; flag the sensitivity |

**Gate G7.3:** both specifications are reported. Silently reporting only the favourable
one is a failure.

### Step 7.4 — Primary vs. extended panel

Refit on the extended panel (SRS §4.5). Report whether R\* is stable.

**Gate G7.4:** the primary-panel result is clearly labelled as primary. The extended
result is presented as a robustness check only.

---

## 8. Stage 2 — Augmented model

Add `dry_run_max`, `dry_days_ge5`, `heat_days`, `vpd_mean`, `rain_days` to the Stage 1
specification.

**Report ΔR² (Stage 2 − Stage 1) per crop.** This is the test of Bal et al. (2022) on
Telangana open data — the project's principal contribution.

- **ΔR² materially positive** → dry-spell duration adds explanatory power beyond
  cumulative rainfall. Report it as the headline finding.
- **ΔR² ≈ 0** → cumulative rainfall is sufficient for these crops. **Report it as the
  headline finding.** Do not bury it.

**Gate G8:** ΔR² is reported for every primary crop regardless of sign or magnitude.

---

## 9. Validation

```
train: ≤ 2019-20      test: ≥ 2020-21
```

**Chronological split only.** Verify absence of random splits:

```bash
grep -rn "train_test_split\|shuffle" src/     # expect: no hits in modelling code
```

Baseline: district-crop 10-year median yield, **fit on train only**.
Metric: `skill = 1 − RMSE_model / RMSE_baseline`.

**Gate G9:** a **positive** skill score is not guaranteed. If skill ≤ 0 the model does not
beat the median — **report that.** "Weather alone does not predict district-level kharif
yield; irrigation and input data would be required" is a publishable finding.

---

## 10. Figures

Style is mandated by SRS §7.1. Non-negotiable:

```python
CMAP_DEFICIT = "YlOrRd"    # drought severity — sequential
CMAP_ANOM    = "RdYlBu"    # yield anomaly — diverging, zero at midpoint
# PROHIBITED: "jet", "rainbow", "hsv", red-green pairings
```

```bash
grep -rn "twinx" src/                      # dual axis — expect zero hits
grep -rniE "jet|rainbow|hsv" src/         # expect zero hits
```

| Figure | File | Gate |
|---|---|---|
| F1 Response curve | `figures/f1_response_curve.png` | Vertex annotated; 2026 dashed marker labelled per SRS §5.6 |
| F2 Time series | `figures/f2_timeseries.png` | Stacked; p10–p90 band; shared x-axis |
| F3 Validation | `figures/f3_validation.png` | Model vs. baseline RMSE |
| F4 Choropleth | `figures/f4_choropleth.png` | `RdYlBu`, post-2016 only, legend with units |

Render every figure in greyscale before delivery to confirm it survives.

**Gate G10:** F1–F4 exist, no `twinx`, no jet/rainbow, all disclosures visible in captions.

---

## 11. Dashboard (Tier 2 — bonus)

**Build only after §10 gates pass.** A beautiful empty shell is worth nothing; the email
ships on the static figures.

Leaflet + D3/Chart.js, static site, no server. Layout per SRS §7.4.
Map default = **yield anomaly (%)**, `RdYlBu`, **fixed domain across all views** —
do not auto-rescale per year.

Commit the dashboard to a `gh-pages`-ready directory. **Do not enable Pages, do not
configure a remote, do not push.** The owner does all of that.

---

## 12. README and disclosures

All **12** mandatory disclosures from SRS §9 must appear. Copy them verbatim; do not
paraphrase downward.

README sections, in order:

1. What this is (2 sentences)
2. Data sources + licence + **attribution**
3. Method (Stage 1, Stage 2, validation)
4. **Results — real numbers, including nulls**
5. Figures
6. **Limitations (all 12)**
7. Reproduction instructions (`DATA_VERSION`, commands)
8. Coordinate source + partition verdict

**Gate G12:** a reviewer who has not seen this conversation can reproduce the numbers from
the README alone.

---

## 13. Commit discipline

**Permitted:** `git status`, `git diff`, `git add <specific paths>`, `git commit`,
`git log`, `git branch`.

**FORBIDDEN (no exceptions):** `git push`, `git remote add`, any command containing
credentials, `--force` in any form, tag creation on the owner's behalf.

Conventional Commits:

```
feat: add Stage 2 augmented model
data: ingest ERA5 for 32 districts, 2001-2023
fix: correct cotton bales/ha unit selection
docs: add all 12 mandatory disclosures to README
```

**One logical change per commit. Never `git add -A`** on a tree with unrelated experiments.

Final verification:

```bash
git log --oneline
git status --porcelain        # expect: clean
```

**Gate G13:** commits exist, working tree clean, **zero push operations performed.**

---

## 14. STOP conditions — halt and report

| # | Condition |
|---|---|
| S1 | Gate G2.1 district counts do not match SRS §4.2 |
| S2 | Gate G2.3 partition verdict cannot be reached — **Tier 2 blocked**, Tier 1 may continue |
| S3 | Gate G6.3 panel does not rebuild byte-identically |
| S4 | Gate G4.4 multi-coordinate block count ≠ requested district count |
| S5 | ERA5 fetch exhausts 8 retries across 3 separate attempts |
| S6 | DES yield counts deviate materially from SRS §5.3 expectations |
| S7 | Any instruction to fabricate, simulate, or estimate a missing value |
| S8 | Any instruction to `git push` |

**On any STOP: write the finding to `data/manifests/BLOCKERS.md`, report it plainly, and
wait.** Do not work around a blocker by weakening the gate.

---

## 15. Definition of done

- [ ] G2.1 district structure verified
- [ ] G2.2 era-tagged district dimension built
- [ ] G2.3 `PARTITION_NOTE.md` written with explicit verdict
- [ ] G2.4 coordinates present and method recorded
- [ ] G3.3 cotton present in bales/ha
- [ ] G4.5 weather cached to raw + interim
- [ ] G6.3 panel reproducible from raw
- [ ] G7.3 both FE specifications reported
- [ ] G8 ΔR² reported for all 3 primary crops
- [ ] G9 chronological split verified; skill reported at any sign
- [ ] G10 F1–F4 exist; no dual axis; no jet/rainbow
- [ ] G12 all 12 disclosures present
- [ ] G13 local commits clean; **no push**

**Tier 1 is complete when this checklist is fully ticked.** The dashboard is optional.