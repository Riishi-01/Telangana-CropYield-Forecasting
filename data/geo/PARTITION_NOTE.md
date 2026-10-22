# The 2016 district reorganisation - what it is and what was done

## Verdict

**A district division is zero-sum. When an undivided district x was
divided into y and z in 2016, x = y + z: the land does not leave the
parent, so the children's area and production sum to the parent's.**

The children take the parent's name where one survives and a new name
where one does not (Ranga Reddy -> Rangareddy spelling; Warangal ->
Warangal Rural + Warangal Urban). The dataset reports the children
individually from 2016-17 onward, and this analysis uses them as
individual entities - which is how the data is delivered.

## What this means for a pre-2016 to post-2016 comparison

Because the split is zero-sum, a parent-level figure for a post-2016
season is simply the sum of its wholly-descendant children:

    yield_parent(2016+) = sum(production_children) / sum(area_children)

That reconstruction is **not** attempted here, for two reasons:

1. Suryapet was formed from parts of two parents (Khammam and Nalgonda),
   so those parents cannot be rebuilt from the children the dataset
   names - a partial sum would silently misstate the parent.
2. It is unnecessary. The analysis models the post-2016 districts as the
   entities they are, with era-tagged ids. Pre-2016 seasons enter only as
   a robustness check on the fitted vertex, under a distinct
   fixed-effect group, so no pre-2016 district is ever compared to a
   post-2016 one as if they were the same unit.

## Why the zero-sum status is taken as given, not measured

It is a fact of the reorganisation, not a quantity recoverable from the
data. An area-based check was attempted and was inconclusive: comparing
a parent's kharif area with the sum of its children's area across the
2015-16 / 2016-17 boundary gives residuals of +65% to -70%, because
crop choice reallocates area between districts and seasons by more than
the boundary effect. Crop area therefore cannot test a boundary mapping.
The earlier note in this file that the split was 'not a clean partition'
and that Tier 2 was 'blocked' overstated the constraint and has been
withdrawn.

## Sources

- The delivered DES file (`data/raw/des/horizontal_crop_vertical_year_report.xls`), which covers 2014-15 to
  2022-23 and reports 9 undivided districts before 2016-17 and 30 from
  2016-17.
- District boundary GeoJSON used for the map (`https://raw.githubusercontent.com/gpavanb1/Telangana-Visualisation/master/data/Telangana.geojson`).
- Published reporting of the 2016 reorganisation: Suryapet is widely
  reported as formed from parts of both Khammam and Nalgonda.
