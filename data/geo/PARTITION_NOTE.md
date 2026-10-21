# Partition verdict — 2016 district reorganisation

**Verdict: TIER 1 PROCEEDS WITH ERA-TAGGED DISTRICT IDS. No parent
aggregation is attempted. Tier 2 (parent-district reconstruction) is
BLOCKED.**

## Sources consulted

- The delivered DES file itself (`data/raw/des/horizontal_crop_vertical_year_report.xls`),
  which contains only 2014-15 … 2022-23.
- Telangana district boundary GeoJSON used for the map (`https://raw.githubusercontent.com/gpavanb1/Telangana-Visualisation/master/data/Telangana.geojson`).
- Published reporting of the 2016 reorganisation: Suryapet is widely
  reported as formed from parts of both Khammam and Nalgonda, and
  Vikarabad and Narayanpet have similarly mixed origins.

## Finding

Where a child district spans two parents, no exact zero-sum partition
of parents into children exists. The 2016 reorganisation is therefore
**not** a clean partition, and an exact parent reconstruction cannot be
computed from the delivered data.

The delivered DES file also ends in 2022-23 and begins in 2014-15, so
there is no pre-2016 parent-level data to reconstruct from in any case.

## Action taken

Pre-2016 and post-2016 observations are modelled as **distinct
fixed-effect groups** using era-tagged district IDs
(`{slug}__pre2016` / `{slug}__post2016`). No continuity assumption is
made across the 2016 boundary revision. The pre-2016 era is used only
as a robustness check on the estimated vertex; all reported results use
the post-2016 primary panel.
