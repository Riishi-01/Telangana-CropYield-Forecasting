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
    ("rice reports a supported optimum R*", "1,355 mm" in r.get("riceFacts", "")),
    ("unmodelled crop is not given a model",
     "none for this crop" in r.get("wheatFacts", "")),
    ("unmodelled crop has no fitted curve",
     "not modelled" in r.get("wheatCurveNote", "")),
    ("season change re-renders the table", r.get("seasonTableRows") == 32),
    ("map note follows the selection", "2018-19" in r.get("mapNote", "")),
    ("metric toggle changes the legend",
     "yield (" in r.get("legendAfterMetric", "")
     and "anomaly" not in r.get("legendAfterMetric", "")),
    ("clicking a table row pins a district", r.get("pinnedRows") == 1),
    ("table sorts ascending", r.get("sortedAscending") is True),
    ("table sorts descending", r.get("sortedDescending") is True),
    ("leaflet drew the district polygons", r.get("leafletPaths", 0) >= 33),
    ("every district carries a value label", r.get("mapLabels") == 33),
    ("response curve rendered", r.get("curvePlot", 0) > 0),
    ("2026 band and marker drawn on the curve", r.get("curveShapes") == 2),
    ("model comparison chart rendered", r.get("statsBars") == 8),
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
