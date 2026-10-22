#!/usr/bin/env bash
# Headless QA for the interactive dashboard.
#
# Serves the dashboard over HTTP (the file:// origin blocks iframe access),
# drives the real controls in headless Chrome, and asserts on the results.
#
# Usage:  bash tests/run_dashboard_qa.sh
# Exit code 0 = all checks pass.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8732}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

cd "$ROOT"
python3 -m http.server "$PORT" --directory "$ROOT" >/tmp/dashboard_qa_http.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
sleep 2

"$CHROME" --headless=new --disable-gpu --no-sandbox --window-size=1500,1300 \
  --virtual-time-budget=30000 --dump-dom "http://127.0.0.1:${PORT}/tests/qa_dashboard.html" \
  2>/dev/null > /tmp/dashboard_qa_dom.html

python3 - "$@" <<'PY'
import html
import json
import re
import sys

doc = open("/tmp/dashboard_qa_dom.html").read()
m = re.search(r'<pre id="out">(.*?)</pre>', doc, re.S)
if not m:
    print("FAIL: the QA harness produced no result")
    sys.exit(1)
payload = m.group(1).strip()
if payload.startswith("QA_RESULT "):
    payload = payload[len("QA_RESULT "):]
try:
    r = json.loads(html.unescape(payload))
except Exception as exc:
    print(f"FAIL: could not parse the QA result: {exc}\n{payload[:400]}")
    sys.exit(1)

if "error" in r:
    print(f"FAIL: {r['error']}")
    sys.exit(1)

checks = [
    ("model facts rendered", "Rainfall optimum" in r.get("defaultFacts", "")),
    ("rice reports a supported optimum R*", re.search(r"R\*\s*[0-9,]+\s*mm", r.get("riceFacts", "")) is not None),
    ("unmodelled crop is not given a model",
     "none for this crop" in r.get("wheatFacts", "")),
    ("map note follows the selection", "2018-19" in r.get("mapNote", "")),
    ("metric toggle changes the legend",
     "yield (" in r.get("legendAfterMetric", "")
     and "anomaly" not in r.get("legendAfterMetric", "")),
    ("rainfall-deficit metric switches the legend",
     "rainfall deficit" in r.get("legendAfterDeficit", "")),
    ("rainfall-deficit legend explains the reference",
     "own" in r.get("legendCaptionDeficit", "").lower()
     and "drought severity" in r.get("legendCaptionDeficit", "").lower()),
    ("leaflet drew the district polygons", r.get("leafletPaths", 0) >= 33),
    ("every district carries a value label", r.get("mapLabels") == 33),
    ("model comparison chart rendered", r.get("statsBars") == 8),
    ("window-sensitivity panel rendered",
     r.get("windowHeadCells") == 4 and r.get("windowBodyRows") == 4),
    ("window panel reports the p-value and the vertex",
     "p =" in r.get("windowFirstRow", "")
     and ("no vertex" in r.get("windowFirstRow", "") or "R*" in r.get("windowFirstRow", ""))),
     ("crop selector offers only the four project crops",
      r.get("cropOptions") == 4),
     ("crop identity strip shows all four crops",
      r.get("cropChips") == 4),
     ("crop identity strip marks exactly one active crop",
      r.get("cropChipActive") == 1),
     ("crop identity colours are the Okabe-Ito palette",
      set(r.get("cropChipColors", [])) == {
        "rgb(0, 158, 115)", "rgb(213, 94, 0)", "rgb(204, 187, 68)",
        "rgb(0, 114, 178)"}),
     ("the 2016 boundary note is visible on the map",
      r.get("boundaryNoteShown") is True
      and "not spatially comparable" in r.get("boundaryNote", "")),
     ("2026 implied range published for rice only",
      r.get("impliedForRice") is True and r.get("impliedWithheld") == 3),
     ("the response-curve chart is retired",
      r.get("curveSectionPresent") is False and r.get("curveHeadingPresent") is False),
     ("the 2018-19 districts table is retired",
      r.get("districtTablePresent") is False and r.get("districtTableHeadPresent") is False),
     ("the four-panel forecast grid is retired",
      r.get("forecastGridPresent") is False),
     ("the forecast is ONE chart", r.get("forecastPlots") == 1 and r.get("forecastSvgs") >= 1),
     ("the crop selector offers All plus the four crops",
      r.get("tickButtons") == 5 and r.get("tickAllText") == "All crops"),
     ("All ticks every crop", r.get("ticksOn") == 5 and r.get("tickPressed") == 5),
     ("the x axis is nine seasons then 2026-27",
      r.get("forecastSeasonCount") == 10 and r.get("forecastLastCategory") is True),
     ("the map opens on the 2026 prediction",
      r.get("defaultSeason") == "2026-27"
      and "2026-27 (prediction)" in r.get("defaultMapNote", "")),
     ("the map opens on cotton and absolute yield",
      r.get("defaultCrop") == "Cotton(lint)" and r.get("defaultMetric") == "yield"),
     ("the 2026 season is offered as a labelled option",
      "2026-27 (prediction)" in r.get("seasonOptions", [])),
     ("every district carries a predicted value on the 2026 map",
      r.get("mapLabelsPredicted") == 33),
     ("the season readout carries the 2026 point, dashed",
      r.get("rainDashed") >= 1 and r.get("yieldDashed") >= 1
      and r.get("rainLastCategory") == "2026-27"
      and r.get("yieldLastCategory") == "2026-27"),
     ("the state summary has five rows",
      r.get("summaryRows") == 5),
     ("the state summary heads 2026 and the state average",
      r.get("summaryHeaders") == ["Crop", "2026", "State avg"]),
     ("the state summary lists the four crops and the rainfall",
      r.get("summaryCrops") == ["Cotton (lint)", "Arhar/Tur", "Moong (green gram)", "Rice", "Kharif rainfall"]),
     ("every state summary row carries its change",
      r.get("summaryDeltas") == 5),
     ("the state summary is in millions",
      all(any("M t" in v or "M bales" in v or "mm" in v for v in row)
          for row in r.get("summaryValues", []))),
     ("the 2026 segment is dashed for every crop",
      r.get("forecastDashed") >= 4),
     ("the chart carries the reference and boundary lines",
      r.get("forecastShapes") >= 2),
     ("the legend explains the marks",
      r.get("forecastLegendItems") >= 5
      and "Telangana average" in r.get("forecastLegendText", "")
      and "2026 prediction" in r.get("forecastLegendText", "")
      and "state yield per hectare" in r.get("forecastLegendText", "")),
     ("the legend names the district observations only when a crop is focused",
      "parent districts" not in r.get("forecastLegendText", "")
      and "parent districts" in r.get("afterUntickLegend", "")),
     ("the foot states the index and the area baseline",
      "indexed" in r.get("forecastFoot", "").lower()
      and "area-weighted" in r.get("forecastFoot", "").lower()
      and "2022-23" in r.get("forecastFoot", "")),
     ("clicking a crop focuses the chart on it",
      r.get("afterUntickOn") == 1 and r.get("afterUntickAll") == 0
      and r.get("afterUntickLines") == 2),
     ("a focused crop shows the district observations",
      r.get("afterUntickPoints") > 0),
     ("the All button ticks every crop back on",
      r.get("afterAllOn") == 5 and r.get("afterAllAll") == 1),
     ("focusing arhar leaves one crop on the chart",
      r.get("arharOn") == 1 and r.get("arharLines") == 2),
     ("the arhar scale ignores the delivered Mulugu outlier",
      r.get("arharYLabels") and max(float(x.replace(",", "")) for x in r["arharYLabels"]) < 200),
     ("the foot reports the off-scale observation",
      "outside the plotted range" in r.get("arharFoot", "")),
     ("forecast table: 32 district rows", r.get("forecastTableRows") == 32),
     ("forecast table: five columns", r.get("forecastTableHeaders") == 5),
     ("forecast table: the difference is tinted both ways",
      r.get("forecastDiffDown") > 0 and r.get("forecastDiffUp") > 0),
     ("forecast table: every difference carries its sign",
      r.get("forecastSignsPrinted") is True),
     ("forecast table: the subtitle names the season and unit",
      "2026-27" in r.get("forecastTableSubtitle", "")
      and "districts" in r.get("forecastTableSubtitle", "")),
     ("point description: the panel populates on selection",
      r.get("detailFields", 0) >= 8),
     ("point description: it reports rainfall",
      r.get("detailHasRainfall") is True),
     ("point description: it names the area baseline",
      r.get("detailHasAreaBaseline") is True),
     ("all 15 disclosures present", r.get("disclosureItems") == 15),
]

failed = 0
for name, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failed += 1

print()
if failed:
    print(f"{failed} check(s) failed")
    sys.exit(1)
print(f"all {len(checks)} dashboard checks passed")
PY
