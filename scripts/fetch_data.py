"""
USDA reefer-availability data acquisition.

This file is the ONLY place that touches the USDA API. It is deliberately
isolated so the API contract is independent of the chart-generation logic.

Source: USDA AMS MyMarketNews MARS API, report slug 2375 — Specialty Crops
National Truck Rate Report (FVWTRK). It carries the weekly 1-5 truck
availability scale (1=Surplus -> 5=Shortage) by origin region, which is
what the chart consumes.

`fetch_data()` returns a pandas DataFrame with AT LEAST these columns:
    Week (int), Quarter (int), Year (int), Region (str), Availability (float)

A CSV fallback is retained for local runs without an API key. Set
DATA_SOURCE=api (the workflow does this by default) to use the live API.
"""
from __future__ import annotations
import os
import sys
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Toggle: "api" once fetch_from_api() is implemented, else "csv".
# Controlled by env var DATA_SOURCE so the workflow can flip it without
# a code change.
# ---------------------------------------------------------------------------
DATA_SOURCE = os.environ.get("DATA_SOURCE", "csv").strip().lower()

# The API key is read from an env var that the GitHub Action injects from
# the repo secret. NEVER hardcode it. Locally you can `export USDA_API_KEY=...`.
USDA_API_KEY = os.environ.get("USDA_API_KEY", "")

# Path to the committed CSV fallback (relative to repo root).
CSV_FALLBACK_PATH = os.environ.get(
    "CSV_FALLBACK_PATH", "data/refrigerated_truck_rates_and_availability.csv"
)

REQUIRED_COLUMNS = ["Week", "Quarter", "Year", "Region", "Availability"]


def fetch_from_api() -> pd.DataFrame:
    """Pull live data from the USDA MyMarketNews MARS API."""
    if not USDA_API_KEY:
        raise RuntimeError(
            "USDA_API_KEY is empty. In GitHub it must be set as a repo secret "
            "and mapped in the workflow env. Locally: export USDA_API_KEY=..."
        )

    # [1] Endpoint: MARS API report slug 2375 = Specialty Crops National
    #     Truck Rate Report (FVWTRK), which exposes the weekly 1-5 reefer
    #     availability series by origin region.
    url = "https://marsapi.ams.usda.gov/services/v1.2/reports/2375"

    # [2] Auth: HTTP Basic, API key as username, empty password.
    auth = (USDA_API_KEY, "")
    headers = {"Accept": "application/json"}

    # [3] MARS filter syntax: q=field=value, ranges use ':'. Pull a wide
    #     window so the per-year dropdown and the 4-year average both have
    #     enough history; end-date is today so the latest week is included.
    today = pd.Timestamp.today().strftime("%m/%d/%Y")
    params = {"q": f"report_begin_date=01/01/2010:{today}"}

    resp = requests.get(url, auth=auth, headers=headers,
                        params=params, timeout=60)
    resp.raise_for_status()

    # [4] Response: {"results": [{report_begin_date, region, availability, ...}, ...]}.
    #     Derive Week / Quarter / Year from report_begin_date and map the
    #     region / availability fields to the canonical column names.
    payload = resp.json()
    records = payload.get("results", payload)
    raw = pd.DataFrame(records)
    if raw.empty:
        raise ValueError(
            "USDA API returned 0 rows for slug 2375. Check the date range "
            "and that the API key is valid."
        )
    raw.columns = [c.lower() for c in raw.columns]

    dates = pd.to_datetime(raw["report_begin_date"], errors="coerce")
    df = pd.DataFrame({
        "Week": dates.dt.isocalendar().week.astype("Int64"),
        "Quarter": dates.dt.quarter.astype("Int64"),
        "Year": dates.dt.year.astype("Int64"),
        "Region": raw["region"],
        "Availability": raw["availability"],
    })
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
