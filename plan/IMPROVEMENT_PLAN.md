# IMPROVEMENT_PLAN.md — Revision & Hardening Pass

**Project:** `telangana-agromet`
**Supersedes:** SRS.md §4.5, §5.4, §5.5, §5.6 and GUIDE.md §7, §9, §10 where noted
**Trigger:** first model run completed; results reviewed; corrections issued

---

## 0. Corrections of record

### V-0 — Verification pass: what was checked against the artefacts, and what changed

This section records the outcome of checking every P0/P1 item in this plan
against the actual shipped artefacts before implementing it. Three items in
this plan were factually wrong and have been corrected here; the rest were
confirmed.

| Item | Plan's claim | What the artefacts show | Action |
|---|---|---|---|
| **P0-1** | The year mapping may be misaligned | **The mapping is correct.** Mahbubnagar 2015-16 rice yielded 2.26 t/ha against a district median of 2.82, and Jun-Sep **2015** delivered 416 mm against Jun-Sep 2016's 1015 mm — the dry window matches the poor yield. Systematically, the same-year alignment maximises \|r\| (mean 0.137 vs 0.107 for +1 yr and 0.037 for −1 yr) and **rice's correlation flips sign** under the +1-yr shift (+0.276 → −0.167) | Gate G1 implemented as an **executable** gate (`src/05_build_panel.py`) that re-fits all three alignments and fails the build if the implemented one is not best. The spot-check row is printed. |
| **P1-7** | "Telangana kharif rainfall essentially never exceeds ~900 mm", so the rice vertex is an extrapolation artefact | **Wrong.** Observed rainfall ranges **363–1,827 mm** (median 891 mm). The 1,354 mm vertex sits inside the observed range, and **11 of 220** district-seasons exceed it | Vertex gate kept (β₂<0 ∧ p<0.05) — it is already implemented and it correctly withheld the vertex for three crops. **Added:** the tail-support count is now reported with the vertex, so the thin tail is visible rather than hidden |
| **P1-10** | "The data for 2001-02 → 2013-14 exists in the same file (9 parent districts throughout)" | **False.** The delivered file's `Year` column contains only 2014-2015 … 2022-2023. There is no pre-2014 data in it | P1-10 **dropped**. The "not enough seasons" hypothesis is recorded as an untested limitation. (Extending the record remains a Tier 2 backlog item, SRS §11) |
| **P1-6 row 2** | The year-shift test must be run | Already run as part of P0-1 | Folded into the grid as the G1 evidence, and **excluded from the robustness count** — a misaligned join can manufacture significance (rice's p₂ passes under the wrong alignment), so counting it would reward a broken join |
| **P2-11** | Add an irrigation covariate | Not done — owner decision | Recorded as the **primary named limitation** (Gate A23 permits the absence to be stated) |

**One correction the owner made to this plan:** C-2 asserted that parent–child
normalisation "IS in use" and superseded the era-tagged design. That was
wrong — see the rewritten C-2 below. The era-tagged design stands.

### C-1 — Data range is **2014-15 → 2022-23**

The shipped model reportedly used "32 districts × 7 seasons, 2016-17 to 2022-23"
(n ≈ 220). The stated project range is **2014-15 → 2022-23**, which is **9 seasons**.

| Period | Seasons | Districts | Obs |
|---|---|---|---|
| 2014-15, 2015-16 | 2 | 9 parent | 18 |
| 2016-17 → 2022-23 | 7 | 32 child | ~224 |
| **Total** | **9** | — | **~242** |

**⚠ ACTION REQUIRED — P0-3.** If the fitted artefact still shows n ≈ 220 / 7 seasons,
the shipped model did **not** use the stated range. Either re-fit on the full
2014-15 → 2022-23 range, or state the actual fitted range in every derived document.
**A stated range that does not match the artefact is a reproducibility failure.**

**Affirmation:** starting at 2014-15 correctly avoids the undivided-Andhra-PRadesh DES
agency discontinuity. That is a sound reason to cut 2001-02 → 2013-14. Keep it.

### C-2 — Parent–child normalisation is **NOT** in use (design confirmed, plan corrected)

**This section superseded the era-tagged-ID design in SRS §4.4. That was wrong;
the era-tagged design stands.** The owner reviewed this and ruled that
era-tagged district IDs are the decided mechanism and that parent aggregation
is not attempted. The reasons are recorded in `data/geo/PARTITION_NOTE.md`:

- A district division is zero-sum: when an undivided district *x* was divided
  into *y* and *z* in 2016, *x = y + z*, so a parent-level figure for a
  post-2016 season is `sum(production_children) / sum(area_children)`.
- The children take the parent's name or a new one (Ranga Reddy → Rangareddy,
  Warangal → Warangal Rural + Warangal Urban) and the dataset reports them
  individually from 2016-17 onward, which is how the panel uses them.
- **The reconstruction is not attempted.** Suryapet was formed from parts of
  two parents (Khammam and Nalgonda), so those parents cannot be rebuilt from
  the children the dataset names. It is also unnecessary: era-tagged fixed
  effects keep pre- and post-2016 districts apart, which is the only
  comparison the analysis makes.
- An area-based check of the zero-sum property was attempted and was
  inconclusive (residuals +65 % to −70 %, swamped by crop choice), so the
  zero-sum status is taken as a **fact of the reorganisation, not a
  measurement**. No numeric claim of exactness is made anywhere.

**Therefore C-2.1 (the exact parent yield identity) is not implemented, and
C-2.2 (parent rainfall aggregation) is not implemented either.** Both were
written as if parent aggregation were the chosen design. The only consequence
is that pre-2016 and post-2016 observations are never compared to each other
directly — which is the intended consequence of the era-tagged design.

C-2.3's "must be verified" requirement is satisfied by the per-district
verdict table in `data/geo/PARTITION_NOTE.md`, not by a parent decomposition.

---

## 1. P0 — Blocking. Complete before any external use.

These are not polish. Each one can invalidate the headline.

### P0-1 — Verify the agricultural-year ↔ calendar-year mapping

**This is the single highest-priority item in the entire plan.**

Telangana defines the agricultural year as **June–May**. DES labels a row `2000-2001`;
under that convention, **kharif = June–September 2000**, not 2001.

**Test:** take Mahbubnagar 2015-2016. Pull Jun–Sep **2015** and Jun–Sep **2016** rainfall.
Whichever better matches the recorded yield identifies the convention.

**Why it matters:** observed rainfall↔yield correlations are `+0.03 (cotton), −0.03
(arhar), −0.16 (moong), +0.07 (rice)`. A one-year shift produces exactly this signature —
all four near zero — because rainfall is strongly autocorrelated between adjacent years.
**A null produced by a misaligned join is not a finding.**

**Gate G1:** the mapping is confirmed in code (a named constant or column transform),
documented, and a spot-check row is printed showing the matched pair.

**If G1 fails**, the entire result set is void and must be re-run before anything is
reported. Do not proceed to writing.

### P0-2 — Rename `C(season)` → `C(year)`

The term has 7–9 levels and only one season is modelled. It is a **year** fixed effect
absorbing statewide annual shocks. Calling it "season" in code, README, or email causes
a reviewer to believe kharif-vs-rabi variation was controlled for. It was not.

**Gate G2:** no variable, label, caption, or sentence uses "season effects" for this term.

### P0-3 — Reconcile stated range with fitted range

Per C-1 above. State the fitted range everywhere, or re-fit.

**Gate G3:** README, the email draft, and `data/manifests/fetch_manifest.json` all agree
on the range actually used.

### P0-4 — Record the parent–child partition decision

Per C-2.3. `data/geo/PARTITION_NOTE.md` must exist with an explicit verdict per affected
district.

**Gate G4:** the note exists and every child district is either uniquely assigned to a
parent or explicitly excluded.

---

## 2. P1 — Required to make the null defensible

### P1-6 — Robustness grid

**The current evidence for the null is one specification.** A null that appears only
under one specification is an artefact until proven otherwise.

Run the headline correlation and Stage-1 slope under all of these:

| # | Specification | Purpose |
|---|---|---|
| 1 | Year mapping as implemented | Baseline |
| 2 | Year mapping shifted ±1 year | **Direct test of P0-1** |
| 3 | With year FE | Current |
| 4 | Without year FE | Does statewide shock drive it? |
| 5 | With district FE | Current — within-district variation |
| 6 | Without district FE (pooled) | Is geography masking the signal? |
| 7 | ERA5-Land 0.1° instead of ERA5 | Resolution sensitivity |

**Interpretation:**

- Null survives **all 7** → robust finding. Report it with the grid shown.
- Null survives **5–6** → report as robust, note the exception.
- Null in **≤4** → the result is specification-dependent. **Report that instead.** Do
  not present a specification-dependent null as a general one.

**Gate G6:** the grid exists as a table in the README with a verdict line.

### P1-7 — Significance test on β₂ before reporting any vertex

The reported `R* = 1,354 mm` sits **at the right edge of the observed data**. Telangana
kharif rainfall essentially never exceeds ~900 mm. The curve in the shipped figure is
flat across 400–1,300 mm.

**The vertex is an extrapolation artifact, not an optimum.**

Per SRS §7.2, report R\* **only if β₂ < 0 AND p < 0.05**. Otherwise the report is:

> "No significant curvature detected in the observed rainfall range (≈350–1,300 mm)."

**Gate G7:** the vertex figure appears **only** if its significance test passes.
Otherwise it is removed from the figure, the abstract, and the email.

### P1-8 — Do not cite failed flexible models as corroboration

The current argument — "ridge and pooled models did worse, so the estimator is not the
limitation" — is **circular**. A flexible model failing to beat a simple one is the *same
single piece of evidence* as the simple model's null. It is not independent confirmation.

This logic holds **only after P0-1 passes.** If the join is sound, then the honest
statement is:

> "No specification tested — including ridge regression and pooled models — recovered a
> rainfall–yield relationship from this record."

That is accurate. The current phrasing implies the null is confirmed by model failure.
It is not.

### P1-9 — District-level slope heterogeneity test

The current model assumes **one shared rainfall slope across all 32 districts**. The
defence is that per-district slopes would be fitted on 7 points.

Correct, but partial pooling resolves it. Use a mixed-effects model with random
intercepts **and random slopes** by district, shrunk toward the global slope. Sparse
groups are exactly what mixed-effects models are designed for.

```
MixedLM(yield ~ rain_mm, groups=district, re_formula="~rain_mm")
```

**Report:** likelihood-ratio test of H₀: all district slopes = 0.

| Result | Statement |
|---|---|
| p > 0.05 | "No evidence that rainfall sensitivity differs across districts." |
| p < 0.05 | Districts respond differently; report which, with shrunken estimates. |

This converts *"we could not estimate it"* into *"we tested it and it is not there."*

**Gate G9:** the LRT p-value is reported, at any value.

### P1-10 — Extend the record back to 2001-02 — **highest-value optional test**

The single most likely explanation for the null is **insufficient record**: 7–9 seasons
cannot resolve a relationship that a 22-year record might.

The data for 2001-02 → 2013-14 exists in the same file (9 parent districts throughout).

```
2014-15 start  →  ~242 obs
2001-02 start  →  ~377 obs
```

**This is a direct test of the "not enough data" hypothesis** and costs one re-fit.

Trade-off: it reintroduces the AP DES agency discontinuity. Run it anyway — if the
conclusion is stable across both starts, the null is very strong. If a signal appears
only in the longer record, **that is the finding, and it is a better one.**

**Gate G10:** both starting points are reported. Stability across them is stated either way.

---

## 3. P2 — Turn the null into a mechanism

### P2-11 — Add an irrigation covariate

**This is the most likely explanation for the null, and the most valuable next step.**

Telangana is heavily borewell-irrigated. Crops recorded as rainfed are irrigated in
distress years, which mechanically attenuates the rainfall→yield relationship. The null
may be real *because of* irrigation.

Add share-of-area-irrigated (or a groundwater-access proxy) as a covariate.

| Outcome | Meaning |
|---|---|
| R² rises materially | Irrigation was the omitted variable. Now you have a **mechanism**, not just a null. |
| R² unchanged | Rainfall genuinely does not drive district-level kharif yield. Equally valid, and now much harder to dismiss. |

Either outcome converts "we could not explain it" into a defensible scientific
statement. Telangana publishes irrigation statistics through the state agriculture
department — record the source in the manifest if used.

**Gate G11:** the covariate is added and R² reported before **and** after. **If the
covariate is unavailable, that must be stated as the limitation** — it is the single
biggest known confound in SRS §9.3 and its absence is not a footnote.

---

## 4. P3 — Framing and product

### P3-12 — 2026 is a diagnostic, not a forecast

The observed findings — rainfall total has no yield relationship; deficit features carry
12–15% variance but are uncalibrated; the naive model produced +91.7% for arhar — do not
support a yield forecast.

**Prohibited in all deliverables:**

| Prohibited | Why |
|---|---|
| A dotted/extended **predicted 2026 yield** line | Asserts a value the evidence does not support |
| `"rainfall −x% → yield −y%"` chaining | Implies causation through a relationship with r ≈ 0.03 |
| **Production totals in tonnes/bales** | Requires a 2026 planted-area figure that does not exist |

**Permitted and expected:**

- 2026 **observed** rainfall (ERA5) as a dashed vertical marker on the fitted curve
- Per-district and per-crop **% deviation from that district's own median yield**
- A visible confidence statement and the §5.6 disclosure

**Required label wherever 2026 appears:**

> "Response curve fitted on 2014-15 – 2022-23 observed yields. 2026 rainfall is ERA5
> observed. Any implied yield is a reading of the fitted relationship, not a validated
> forecast. The model reports no significant rainfall–yield relationship for these crops."

### P3-13 — Do not shrink an uncalibrated model

Applying a fitted shrinkage factor (e.g. 0.65) to an uncalibrated deficit model produces
a **smaller incorrect number**, not a correct one. `arhar +91.7% → +39%` is still not a
defensible forecast; it is a large number with more decimal places.

If a shrinkage factor is used anywhere, it must be **calibrated on held-out data and
reported with its own validation error**. Otherwise it does not ship.

### P3-14 — The null is the deliverable

The email is:

> *"I set out to test whether kharif rainfall drives district-level crop yield in
> Telangana. It largely does not — here is the evidence, the robustness checks, the most
> likely explanation, and what data would be needed to answer it properly."*

This fully repairs the earlier overclaiming and is a stronger letter than any forecast
that could be manufactured on top of it. Do not dilute it with a headline number.

---

## 5. P4 — Visualisation corrections

### P4-15 — 2026 as a band, never a dashed line

A dashed line asserts a specific value. A shaded band asserts uncertainty. Render 2026
as the **% vs district normal range**, with the point estimate as a marker inside it.

### P4-16 — Crop colour system — Okabe-Ito

Colourblind-safe, domain-appropriate, **identical across every chart and selector**:

| Crop | Hex | Basis |
|---|---|---|
| Rice | `#009E73` | paddy green |
| Arhar/Tur | `#D55E00` | tur dal vermillion |
| Moong | `#CCBB44` | green gram yellow-green |
| Cotton | `#0072B2` | boll blue |

A crop's colour **never changes** when switching selectors. Red/green pairings remain
prohibited.

### P4-17 — Map must show the boundary discontinuity

The choropleth plots 32 post-2016 districts. Add an explicit note that pre-2016
observations are parent-district aggregates and **not spatially comparable** to the
post-2016 layer. A viewer who doesn't know this will misread the map.

### P4-18 — Relabel the 2026 marker on the scatter

Current: "2026 rainfall on the fitted curve."
Required: **"2026 position on fitted curve — no significant relationship detected."**

---

## 6. Execution order

```
P0-1  verify year mapping ◄── STOP: everything else is void if this fails
P0-2  rename C(season) → C(year)
P0-3  reconcile stated vs fitted range
P0-4  record partition decision

P1-6  robustness grid (7 specs)
P1-7  β₂ significance → vertex or drop
P1-9  partial-pooling heterogeneity test
P1-10 re-fit from 2001-02

P2-11 irrigation covariate          ← turns null into mechanism

P3    framing + figures
P4    visualisation corrections
```

**Gate between P0 and P1:** P0-1 must pass. A failure there invalidates all downstream
work — stop, fix the join, re-run.

---

## 7. Updated acceptance criteria

Existing SRS §10 criteria remain in force. Additionally:

| # | Criterion |
|---|---|
| **A16** | Agricultural-year ↔ calendar-year mapping verified in code and documented |
| **A17** | No artifact uses the term "season effects" for the year fixed effect |
| **A18** | Stated range matches fitted range in all three places (README, manifest, email) |
| **A19** | `PARTITION_NOTE.md` assigns or excludes every affected child district |
| **A20** | Robustness grid reported with an explicit verdict line |
| **A21** | Vertex reported **iff** β₂ < 0 and p < 0.05 — otherwise explicitly stated as not detected |
| **A22** | Heterogeneity LRT p-value reported |
| **A23** | Irrigation covariate result reported, **or** its absence stated as the primary limitation |
| **A24** | No production tonnage forecast anywhere in the deliverable |
| **A25** | 2026 rendered as a band; no dashed predicted-yield line |

---

## 8. Honest statement of what remains unknown

- Whether the 2016 reorganisation admits an exact zero-sum partition — **unresolved**
- Whether the null survives a 22-year record — **untested** (P1-10 would answer it)
- Whether irrigation explains the null — **untested** (P2-11 would answer it)
- Whether the DES 2023-24 / 2024-25 releases exist and would extend the record — **unverified**

These are not defects. They are the natural boundaries of a single-analyst analysis on
open data, and stating them is the correct scientific posture — not covering them with a
forecast the data cannot support.

## 9. Implementation log — what was done, and what each item produced

All P0 and P1 items below are implemented. The plan's own factual errors are
recorded in §0 V-0 and were corrected in this file rather than silently obeyed.

| Item | Outcome | Where |
|---|---|---|
| **P0-1** year mapping | **Verified and made executable.** `common.YEAR_MAPPING` names the convention; `common.verify_year_mapping()` re-fits under three alignments and fails the build if the implemented one is not best. It passes (mean \|r\| 0.137 vs 0.107 and 0.037; rice flips sign under +1 yr). The Mahbubnagar spot-check prints at build time. | `src/common.py`, `src/05_build_panel.py` |
| **P0-2** `C(season)` → `C(year)` | Done. Panel column `season_year` → `year`; term `C(year)`; key `no_season_fe` → `no_year_fe`; all prose now says "year fixed effects". The design matrix is numerically identical and every coefficient is unchanged. | 13 source files, `README.md`, dashboard |
| **P0-3** fitted range | `model_summary.json` gained `fitted_range` (seasons, years, n, districts) and `dataset_range`; `fetch_manifest.json` gained `year_mapping` and a `fitted_range_note`. The stale `2001-02` references in SRS §4.4/§4.5/§5.6, GUIDE Step 2.2 and the SRS §5.3 crop-group claim were corrected. | `src/06_model_stage1.py`, `src/05_build_panel.py`, `plan/SRS.md`, `plan/GUIDE.md` |
| **P0-4** partition record | The plan's C-2 was rewritten to the decided era-tagged design, and `PARTITION_NOTE.md` gained the per-district disposition table (all 32 post-2016 districts, the 9 pre-2016 parents, the 22 new districts, and explicit notes for Suryapet and Warangal). | `plan/IMPROVEMENT_PLAN.md`, `data/geo/PARTITION_NOTE.md` |
| **P1-6** robustness grid | `src/13_robustness_grid.py` runs 6 specifications (row 7 deferred to Tier 2) and reports a verdict per crop. **Key result: rice survives within-district (3/4); cotton's only significance is in the pooled fit, i.e. a between-district confound.** The shift row is excluded from the count because a misaligned join can manufacture significance. | `src/13_robustness_grid.py`, `README.md` §5.1 |
| **P1-7** vertex gate | The β₂ gate was already implemented and correctly withheld the vertex for three crops. The plan's premise was wrong and is corrected. **Added:** the tail-support count (11 of 220 district-seasons above the rice vertex) is now reported with it. | `src/06_model_stage1.py`, `README.md` §5.1 |
| **P1-8** no circular corroboration | Rewritten. The README now states what was and was not tested, and does not present a flexible model's failure as independent confirmation. | `README.md` §5.1 |
| **P1-9** slope heterogeneity | `src/14_slope_heterogeneity.py` fits `MixedLM(..., re_formula="~rain_mm")` and reports the LRT of H₀ (random-slope variance = 0). **All four crops: no evidence that district slopes differ** (p = 0.076, 0.087, 0.600, 0.789). The optimiser matters and is documented: the default L-BFGS lands in a local optimum and yields a negative LRT, so Powell is used with fallbacks. | `src/14_slope_heterogeneity.py`, `README.md` §5.1 |
| **P1-10** extend to 2001-02 | **Dropped — the data does not exist.** The delivered file holds 2014-15 … 2022-23 only. The "not enough seasons" hypothesis is recorded as an untested limitation. | `README.md` §7.13 |
| **P2-11** irrigation | Not added, by owner decision. Its absence is stated as the **primary limitation** at the top of the README, in the limitations list, in the F1 caption and in the dashboard disclosures. | `README.md`, `src/09_figures.py`, `src/10_build_dashboard.py` |
| **P3-12** 2026 as a diagnostic | Implemented. 2026 is a band with the point estimate inside it; no production tonnage anywhere; the mandated label is corrected and now says the fitted range is 2016-17 – 2022-23. **The implied range is published for rice only** — for arhar the reading produced negative yields for 6 of 32 districts, which is withheld with a stated reason. | `src/common.py`, `src/09_figures.py`, `src/10_build_dashboard.py`, `dashboard/assets/app.js` |
| **P3-13** no uncalibrated shrinkage | No shrinkage factor ships. The only shrinkage anywhere is the lambda in the mixed-effects model, which is estimated by the fit itself. | — |
| **P3-14** the deliverable | Rewritten. It is not a blanket null: it is a **split** — rice responds, the other three do not, and the relationship is too small to forecast. | `README.md` top |
| **P4-15** 2026 as a band | Implemented in F1 and in the dashboard: a shaded band with the state-mean point estimate inside it, replacing the dashed assertion. | `src/09_figures.py`, `dashboard/assets/app.js` |
| **P4-16** Okabe-Ito crop colours | Added to SRS §7.1 and `common.CROP_COLORS`; shipped in the dashboard bundle, rendered as a crop identity strip under the selector, and used for each crop's curve in F1. A crop's colour never changes with the selector. | `plan/SRS.md`, `src/common.py`, `src/09_figures.py`, `src/10_build_dashboard.py`, `dashboard/` |
| **P4-17** boundary discontinuity | A note is now rendered **on the map itself**, stating that the layer is the 32 post-2016 districts and that the two pre-2016 seasons are 9 undivided parents and not spatially comparable. | `dashboard/index.html`, `dashboard/assets/styles.css` |
| **P4-18** marker relabel | The F1 and dashboard labels now read "2026 position on fitted curve" with the % vs normal and its band, or "no implied yield for this crop" where the curve has no supported shape. | `src/09_figures.py`, `dashboard/assets/app.js` |
| **A16–A25** | All implemented and gated. The verifier grew from 134 to **164** checks; the dashboard QA grew from 29 to **34**. | `tests/` |

**One thing this pass changed about the conclusion.** The plan was written on the
assumption that no crop showed a rainfall–yield relationship. That is not what
the data says: **rice responds** (within-district r = +0.221, p = 0.001;
quadratic p = 0.018), and the relationship survives the robustness grid. The
plan's P3-14 framing ("the null is the deliverable") is therefore wrong as
written, and the deliverable is a split result rather than a null. What survives
of P3-14's instinct is the discipline: no production tonnage, no predicted-yield
line, and a visible confidence statement.

---

