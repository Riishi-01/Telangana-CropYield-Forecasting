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
    ("table rows on load (32 districts)", r.get("defaultTableRows") == 32),
    ("model facts rendered", "Rainfall optimum" in r.get("defaultFacts", "")),
    ("curve note rendered", "rainfall" in r.get("defaultCurveNote", "").lower()),
    ("2026 disclaimer visible in the DOM", r.get("disclaimerVisible") is True),
    ("disclaimer states it is not a forecast",
     "not a validated forecast" in r.get("disclaimer", "")),
    ("rice reports a supported optimum R*", re.search(r"R\*\s*[0-9,]+\s*mm", r.get("riceFacts", "")) is not None),
    ("unmodelled crop is not given a model",
     "none for this crop" in r.get("wheatFacts", "")),
    ("unmodelled crop has no fitted curve",
     "not modelled" in r.get("wheatCurveNote", "")),
    ("season change re-renders the table", r.get("seasonTableRows") == 32),
    ("map note follows the selection", "2018-19" in r.get("mapNote", "")),
    ("metric toggle changes the legend",
     "yield (" in r.get("legendAfterMetric", "")
     and "anomaly" not in r.get("legendAfterMetric", "")),
    ("rainfall-deficit metric switches the legend",
     "rainfall deficit" in r.get("legendAfterDeficit", "")),
    ("rainfall-deficit legend explains the reference",
     "own" in r.get("legendCaptionDeficit", "").lower()
     and "drought severity" in r.get("legendCaptionDeficit", "").lower()),
    ("table columns follow the metric (deficit)",
     "Rain deficit (%)" in r.get("tableHeadersDeficit", [])),
    ("table columns follow the metric (yield)",
     "Anomaly" not in " ".join(r.get("tableHeadersYield", []))),
    ("deficit values are numeric for every district",
     r.get("deficitAllNumeric") is True and len(r.get("deficitValues", [])) == 32),
    ("deficit is centred on the district's own norm (mean near 0)",
     abs(r.get("deficitMean", 99)) < 25),
    ("clicking a table row pins a district", r.get("pinnedRows") == 1),
    ("table sorts ascending", r.get("sortedAscending") is True),
    ("table sorts descending", r.get("sortedDescending") is True),
    ("leaflet drew the district polygons", r.get("leafletPaths", 0) >= 33),
    ("every district carries a value label", r.get("mapLabels") == 33),
    ("response curve rendered", r.get("curvePlot", 0) > 0),
    ("2026 band and marker drawn on the curve", r.get("curveShapes") == 2),
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
     ("all 12 disclosures present", r.get("disclosureItems") == 12),
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
