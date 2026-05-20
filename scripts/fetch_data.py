"""
USDA reefer-availability data acquisition.

This file is the ONLY place that touches the USDA API. It is deliberately
isolated so the API contract is independent of the chart-generation logic.

Source: USDA AMS Specialty Crops Program via Socrata at agtransport.usda.gov,
dataset acar-e3r8 — "Refrigerated Truck Rates and Availability". It carries
the weekly 1-5 truck availability scale (1=Surplus -> 5=Shortage) by origin
region, which is what the chart consumes.

`fetch_data()` returns a pandas DataFrame with AT LEAST these columns:
    Week (int), Quarter (int), Year (int), Region (str), Availability (float)

A CSV fallback is retained for local runs without network. Set DATA_SOURCE=api
(the workflow does this by default) to use the live Socrata API.
"""
from __future__ import annotations
import os
import sys
import time
from typing import Any

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Toggle: "api" hits the Socrata endpoint, anything else falls back to the
# bundled CSV. Controlled by env var DATA_SOURCE so the workflow can flip
# it without a code change.
# ---------------------------------------------------------------------------
DATA_SOURCE = os.environ.get("DATA_SOURCE", "csv").strip().lower()

# App token is OPTIONAL — the dataset is public; the token only raises rate
# limits. In GitHub it is mapped from the SOCRATA_APP_TOKEN repo secret.
SOCRATA_APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN") or None

# Path to the committed CSV fallback (relative to repo root).
CSV_FALLBACK_PATH = os.environ.get(
    "CSV_FALLBACK_PATH", "data/refrigerated_truck_rates_and_availability.csv"
)

REQUIRED_COLUMNS = ["Week", "Quarter", "Year", "Region", "Availability"]

# Socrata dataset: Refrigerated Truck Rates and Availability.
#   https://agtransport.usda.gov/Truck/Refrigerated-Truck-Rates-and-Availability/acar-e3r8/data
SOCRATA_DOMAIN = "agtransport.usda.gov"
DATASET_ID = "acar-e3r8"
API_URL = f"https://{SOCRATA_DOMAIN}/resource/{DATASET_ID}.json"
PAGE_SIZE = 10_000

# Year window exposed by the chart's Year dropdown (inclusive). Both fetch
# paths clip to this range so the dropdown only ever lists these years.
YEAR_MIN = 2022
YEAR_MAX = 2025


_GREAT_LAKES = {"GREAT LAKES", "MICHIGAN", "WISCONSIN", "MINNESOTA",
                "OHIO", "INDIANA", "ILLINOIS"}
_MID_ATLANTIC = {"MID-ATLANTIC", "PENNSYLVANIA", "NEW JERSEY", "DELAWARE",
                 "MARYLAND", "VIRGINIA", "WEST VIRGINIA"}
_SOUTHEAST = {"SOUTHEAST", "NORTH CAROLINA", "SOUTH CAROLINA", "GEORGIA",
              "ALABAMA", "TENNESSEE", "KENTUCKY"}
_PNW = {"PNW", "PACIFIC NORTHWEST", "WASHINGTON", "OREGON", "IDAHO"}


def normalize_region(raw: str) -> str | None:
    """Map raw Socrata region strings to the canonical names the chart uses.
    Returns None for rows whose region we don't recognize so the caller can
    drop them."""
    u = (raw or "").strip().upper()
    if not u:
        return None
    if u.startswith("MEXICO-CALIFORNIA"):
        return "Mexico-California"
    if u.startswith("MEXICO-ARIZONA"):
        return "Mexico-Arizona"
    if u.startswith("MEXICO-TEXAS"):
        return "Mexico-Texas"
    if u.startswith("MEXICO-NEW MEXICO") or u.startswith("MEXICO-NM"):
        return "Mexico-New Mexico"
    if u.startswith("CALIFORNIA"):
        return "California"
    if u in _PNW:
        return "PNW"
    if u == "ARIZONA":
        return "Arizona"
    if u == "COLORADO":
        return "Colorado"
    if u == "FLORIDA":
        return "Florida"
    if u == "NEW YORK":
        return "New York"
    if u == "TEXAS":
        return "Texas"
    if u in _GREAT_LAKES:
        return "Great Lakes"
    if u in _MID_ATLANTIC:
        return "Mid-Atlantic"
    if u in _SOUTHEAST:
        return "Southeast"
    return None


def _get_with_retry(
    url: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
    max_retries: int = 5,
) -> requests.Response:
    retryable = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    )
    for attempt in range(max_retries + 1):
        try:
            return requests.get(url, params=params, headers=headers, timeout=timeout)
        except retryable as e:
            if attempt == max_retries:
                raise
            backoff = 2 ** (attempt + 1)
            print(
                f"    {type(e).__name__} on attempt {attempt + 1}/{max_retries + 1}; "
                f"retrying in {backoff}s ...",
                file=sys.stderr, flush=True,
            )
            time.sleep(backoff)
    raise RuntimeError("unreachable")


def fetch_from_api() -> pd.DataFrame:
    """Pull live data from the USDA AMS Socrata dataset acar-e3r8.

    Returns a flat DataFrame: one row per source observation, with the
    canonical Week/Quarter/Year/Region/Availability columns. The chart layer
    filters to a specific quarter itself — this layer pulls the full history
    so the Year dropdown can offer multiple years."""
    headers: dict[str, str] = {"Accept": "application/json"}
    if SOCRATA_APP_TOKEN:
        headers["X-App-Token"] = SOCRATA_APP_TOKEN

    rows: list[dict[str, Any]] = []
    offset = 0
    # Server-side year filter — keeps the download to the 4 years the chart
    # actually exposes in its Year dropdown.
    where = f"date_extract_y(date) BETWEEN {YEAR_MIN} AND {YEAR_MAX}"
    while True:
        params: dict[str, Any] = {
            "$limit": PAGE_SIZE,
            "$offset": offset,
            "$order": ":id",
            "$where": where,
        }
        print(f"[fetch_data] page offset={offset:>7} ",
              end="", file=sys.stderr, flush=True)
        r = _get_with_retry(API_URL, params=params, headers=headers, timeout=300)
        if r.status_code != 200:
            raise RuntimeError(
                f"Socrata HTTP {r.status_code} for {DATASET_ID}: {r.text[:300]}"
            )
        batch = r.json()
        print(f"({len(batch):>5} rows)", file=sys.stderr)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += len(batch)
        if offset > 5_000_000:
            print("[fetch_data] safety cap hit; stopping.", file=sys.stderr)
            break

    if not rows:
        raise ValueError(
            f"Socrata returned 0 rows for {DATASET_ID}. Check that the dataset "
            f"is still published at {API_URL}."
        )

    raw = pd.DataFrame(rows)
    # The dataset exposes week, quarter, year, region, availability as their
    # own columns — use them directly rather than re-deriving from `date`.
    df = pd.DataFrame({
        "Week": pd.to_numeric(raw["week"], errors="coerce").astype("Int64"),
        "Quarter": pd.to_numeric(raw["quarter"], errors="coerce").astype("Int64"),
        "Year": pd.to_numeric(raw["year"], errors="coerce").astype("Int64"),
        "Region": raw["region"].map(normalize_region),
        "Availability": pd.to_numeric(raw["availability"], errors="coerce"),
    })
    # Drop rows whose region we don't recognize or whose availability isn't a
    # valid 1-5 rating; everything else falls through to _normalize().
    df = df[df["Region"].notna() & df["Availability"].between(1, 5)]
    return _normalize(df)


def fetch_from_csv() -> pd.DataFrame:
    """Fallback: read the committed CSV export. Lets CI run before the
    API is wired in. This matches the data file used during development."""
    if not os.path.exists(CSV_FALLBACK_PATH):
        raise FileNotFoundError(
            f"CSV fallback not found at {CSV_FALLBACK_PATH}. Either commit the "
            f"CSV there, or set DATA_SOURCE=api once fetch_from_api() is done."
        )
    df = pd.read_csv(CSV_FALLBACK_PATH, usecols=lambda c: c in REQUIRED_COLUMNS)
    df = df[pd.to_numeric(df["Year"], errors="coerce").between(YEAR_MIN, YEAR_MAX)]
    return _normalize(df)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce to the canonical schema regardless of source. This is the
    contract the rest of the pipeline depends on — keep it strict so a
    bad API response fails loudly here, not silently in the chart."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Data is missing required columns {missing}. "
            f"Got columns: {list(df.columns)}. "
            f"Adjust the parsing in fetch_from_api() to map to: "
            f"{REQUIRED_COLUMNS}"
        )
    out = df[REQUIRED_COLUMNS].copy()
    for col in ["Week", "Quarter", "Year"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    out["Availability"] = pd.to_numeric(out["Availability"], errors="coerce")
    out["Region"] = out["Region"].astype(str).str.strip()
    out = out.dropna(subset=["Week", "Quarter", "Year", "Availability"])
    if out.empty:
        raise ValueError("After normalization the dataset is empty — check "
                          "the source/parsing.")
    return out


def fetch_data() -> pd.DataFrame:
    """Single entry point used by build_chart.py."""
    src = "api" if DATA_SOURCE == "api" else "csv"
    print(f"[fetch_data] source = {src}", file=sys.stderr)
    df = fetch_from_api() if src == "api" else fetch_from_csv()
    print(f"[fetch_data] {len(df):,} rows, "
          f"years {int(df.Year.min())}-{int(df.Year.max())}, "
          f"{df.Region.nunique()} regions", file=sys.stderr)
    return df


if __name__ == "__main__":
    # Quick local smoke test: python scripts/fetch_data.py
    d = fetch_data()
    print(d.head())
    print(d.dtypes)
