"""Shared paths, constants and helpers for the telangana-agromet pipeline.

Authority: plan/SRS.md, plan/GUIDE.md.
Every script in src/ imports from here so that paths, seeds, colour rules and
provenance handling are defined in exactly one place.

Determinism: run every script as
    PYTHONHASHSEED=0 .venv/bin/python src/<script>.py
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_DES = RAW / "des"
RAW_OPENMETEO = RAW / "openmeteo"
RAW_GEO = RAW / "geo"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
GEO = DATA / "geo"
MANIFESTS = DATA / "manifests"

FIGURES = ROOT / "figures"
DASHBOARD = ROOT / "dashboard"
DASHBOARD_DATA = DASHBOARD / "data"
DASHBOARD_ASSETS = DASHBOARD / "assets"
DASHBOARD_VENDOR = DASHBOARD_ASSETS / "vendor"

DATA_VERSION_FILE = ROOT / "DATA_VERSION"

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
SEED = 0

# Source file delivered with the project (immutable, never edited).
DES_SOURCE = DATA / "horizontal_crop_vertical_year_report.xls"
DES_RAW_COPY = RAW_DES / "horizontal_crop_vertical_year_report.xls"

# Weather (SRS §3.2)
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_MODEL = "era5"  # ERA5 reanalysis via the Open-Meteo archive API
WEATHER_LICENCE = "CC BY 4.0 (ERA5 via Open-Meteo)"

# Windows (SRS §5.1, amended by plan/ERRATA.md for the actual DES coverage)
INGEST_START = "2014-06-01"
INGEST_END = "2023-10-31"
ANALYSIS_START_MMDD = (6, 1)
ANALYSIS_END_MMDD = (9, 30)
FEATURE_WINDOW_END_MMDD = (10, 31)  # dry-spell features use Jun 1 - Oct 31

# Marker window for the 2026 rainfall reading (SRS §5.6)
MARKER_YEAR = 2026
MARKER_START = "2026-06-01"
MARKER_END = "2026-09-30"

# Panel definitions (plan/ERRATA.md C1)
PRIMARY_PANEL_START = "2016-17"
EXTENDED_PANEL_START = "2014-15"

# Crops (SRS §5.3)
PRIMARY_CROPS = ["Cotton(lint)", "Arhar/Tur", "Moong(Green Gram)"]
SECONDARY_CROPS = ["Rice"]
MODELLED_CROPS = PRIMARY_CROPS + SECONDARY_CROPS

# Validation (SRS §5.5) - chronological split only, never random.
TRAIN_LAST_SEASON = "2019-20"
TEST_FIRST_SEASON = "2020-21"

# Colour system (SRS §7.1) - red/green pairings and rainbow maps are prohibited.
CMAP_DEFICIT = "YlOrRd"  # sequential, drought severity
CMAP_ANOM = "RdYlBu"  # diverging, zero pinned to the exact midpoint
C_CURVE = "#1f77b4"
C_RAIN = "#4C78A8"
C_YIELD = "#E45756"
C_MARKER_2026 = "#111111"

# Mandatory disclosure strings (SRS §5.6, §9)
DISCLOSURE_2026 = (
    "Response curve fitted on observed kharif yields. 2026 rainfall is ERA5 observed. "
    "Any implied yield is a reading of the fitted curve, not a validated forecast - "
    "the extrapolation gap is 3+ years."
)
DISCLOSURE_ERA5 = (
    "Reanalysis, not observation. ERA5 is a model-assimilated reanalysis product at "
    "0.25 deg (~25 km) resolution. It is not IMD station gauge data."
)


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #
def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp, second resolution, used in every manifest."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dirs() -> None:
    for d in (
        RAW_DES,
        RAW_OPENMETEO,
        RAW_GEO,
        INTERIM,
        PROCESSED,
        GEO,
        MANIFESTS,
        FIGURES,
        DASHBOARD_DATA,
        DASHBOARD_ASSETS,
        DASHBOARD_VENDOR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def data_version() -> str:
    if DATA_VERSION_FILE.exists():
        return DATA_VERSION_FILE.read_text().strip()
    return "0.0.0"


def write_json(path: Path | str, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def read_json(path: Path | str):
    return json.loads(Path(path).read_text())


def season_to_year_start(season: str) -> int:
    """'2014 - 2015' or '2014-15' -> 2014 (the year the kharif season opens)."""
    return int(str(season).split("-")[0].strip())


def season_label(year_start: int) -> str:
    """2014 -> '2014-15'."""
    return f"{year_start}-{str(year_start + 1)[-2:]}"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Network: curl-based fetch with mandatory retry (GUIDE §4.1)
# --------------------------------------------------------------------------- #
# The Open-Meteo archive endpoint intermittently fails with SSL_ERROR_SYSCALL
# through this network path. urllib fails on nearly every request while curl
# succeeds, so curl is the transport. Retries are mandatory, not optional.
#
# Retry policy:
#   * HTTP 200 + non-empty body  -> success
#   * HTTP 000 (network/SSL drop) -> pause 5 s, retry
#   * HTTP 429 (rate limited)     -> long shared cooldown (60 s), retry
#   * HTTP 4xx/5xx otherwise      -> pause 5 s, retry
#
# The 5 s pause on SSL/network failures is deliberate: an immediate retry
# re-hits a broken TLS path and the failure repeats. The pause lets the
# connection pool and TLS session recover.


class FetchError(RuntimeError):
    pass


def _retry_delay(code: str, body: str, attempt: int, pause: float) -> float:
    """Seconds to wait before the next attempt.

    HTTP 429 from the Open-Meteo archive API is a *quota* signal, not a
    transient error.  The free tier answers with
    {"reason": "Hourly API request limit exceeded. Please try again in the next
    hour."}, so the correct response is to wait for the top of the next hour
    rather than to hot-loop.  A shorter generic 429 (no hourly wording) gets
    a 60 s cooldown.  Everything else gets a linear backoff of 5 s, 10 s, ...
    """
    if code == "429":
        if "hour" in (body or "").lower():
            now = datetime.now(timezone.utc)
            nxt = now.replace(minute=0, second=0, microsecond=0)
            nxt = nxt.replace(hour=(nxt.hour + 1) % 24)
            wait = max(60.0, (nxt - now).total_seconds() + 30)
            return min(wait, 3600.0)
        return 60.0
    return pause * attempt


def fetch(url: str, tries: int = 8, timeout: int = 60, pause: float = 5.0) -> dict:
    """GET a JSON document via curl, retrying transient failures.

    Returns the decoded JSON body. Raises FetchError when the retry budget is
    exhausted. The raw body is never mutated here - callers cache it verbatim
    into data/raw/ before any processing (GUIDE §4.5).
    """
    last_status = "000"
    last_err = ""
    for attempt in range(1, tries + 1):
        proc = subprocess.run(
            ["curl", "-sS", "-m", str(timeout), "-w", "\n%{http_code}", url],
            capture_output=True,
            text=True,
        )
        body, _, code = proc.stdout.rpartition("\n")
        code = code.strip() or "000"
        last_status = code
        if code == "200" and body.strip():
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:  # truncated body
                last_err = f"invalid JSON: {exc}"
        else:
            last_err = (proc.stderr or "").strip()[:200]

        if attempt == tries:
            break

        wait = _retry_delay(code, body, attempt, pause)
        log(
            f"    fetch attempt {attempt}/{tries} failed (HTTP {code}"
            f"{'; ' + last_err if last_err else ''}) -> sleeping {wait:.0f}s"
        )
        time.sleep(wait)

    raise FetchError(
        f"exhausted {tries} attempts for {url[:120]} (last HTTP {last_status}: {last_err})"
    )


def curl_text(url: str, tries: int = 8, timeout: int = 60, pause: float = 5.0) -> str:
    """Same retry policy as fetch() but returns the raw text body."""
    last_status = "000"
    last_err = ""
    for attempt in range(1, tries + 1):
        proc = subprocess.run(
            ["curl", "-sSL", "-m", str(timeout), "-w", "\n%{http_code}", url],
            capture_output=True,
            text=True,
        )
        body, _, code = proc.stdout.rpartition("\n")
        code = code.strip() or "000"
        last_status = code
        if code == "200" and body.strip():
            return body
        last_err = (proc.stderr or "").strip()[:200]
        if attempt == tries:
            break
        wait = _retry_delay(code, body, attempt, pause)
        log(
            f"    fetch attempt {attempt}/{tries} failed (HTTP {code}"
            f"{'; ' + last_err if last_err else ''}) -> sleeping {wait:.0f}s"
        )
        time.sleep(wait)
    raise FetchError(
        f"exhausted {tries} attempts for {url[:120]} (last HTTP {last_status}: {last_err})"
    )


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
def check_determinism() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        log("WARNING: PYTHONHASHSEED is not 0 - results may not be byte-reproducible")
