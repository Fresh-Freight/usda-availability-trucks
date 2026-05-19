"""
USDA reefer-availability data acquisition.

IMPORTANT — READ THIS:
This file is the ONLY place that touches the USDA API. It is deliberately
isolated so you can drop in the real API contract without touching the
chart-generation logic.

I do NOT know the real USDA API shape (base URL, auth header, endpoint
paths, response schema) — that was never reachable during development and
the data provided was a CSV export. So `fetch_from_api()` below is a
TEMPLATE with the standard patterns marked. Fill in the 4 marked spots.

`fetch_data()` returns a pandas DataFrame with AT LEAST these columns:
    Week (int), Quarter (int), Year (int), Region (str), Availability (float)

A CSV fallback is included so the pipeline runs end-to-end TODAY even
before the API wiring is done. Set USE_API=True (or env DATA_SOURCE=api)
once your fetch_from_api() is filled in.
"""
from __future__ import annotations
import os
import io
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
    """
    Pull live data from the USDA API.

    >>> FILL IN THE 4 MARKED SPOTS BELOW <<<

    The structure (request -> check -> parse -> normalize) is correct and
    standard; only the USDA-specific details are unknown to me.
    """
    if not USDA_API_KEY:
        raise RuntimeError(
            "USDA_API_KEY is empty. In GitHub it must be set as a repo secret "
            "and mapped in the workflow env. Locally: export USDA_API_KEY=..."
        )

    # [1] REAL ENDPOINT — replace with the actual USDA API URL.
    url = "https://REPLACE-WITH-REAL-USDA-API-ENDPOINT"

    # [2] AUTH — USDA APIs commonly use one of these. Keep the one that
    #     matches your API's docs; delete the others.
    headers = {
        "Authorization": f"Bearer {USDA_API_KEY}",   # bearer-token style
        # "X-Api-Key": USDA_API_KEY,                  # api-key-header style
        "Accept": "application/json",
    }
    params = {
        # "api_key": USDA_API_KEY,                    # query-param style
        # [3] QUERY PARAMS — date range, dataset id, format, etc.
        # e.g. "commodity": "refrigerated-truck", "format": "json",
    }

    resp = requests.get(url, headers=headers, params=params, timeout=60)
    resp.raise_for_status()

    # [4] RESPONSE PARSING — adapt to the real schema. Two common shapes:
    #
    #   a) JSON records:
    #        payload = resp.json()
    #        df = pd.DataFrame(payload["results"])   # adjust the key
    #
    #   b) CSV body:
    #        df = pd.read_csv(io.StringIO(resp.text))
    #
    # Using (a) as the default guess:
    payload = resp.json()
    records = payload.get("results", payload)  # tolerate either shape
    df = pd.DataFrame(records)

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
