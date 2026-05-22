"""
Builds the regional Q3 reefer capacity divergence chart as index.html.

Pulls fresh data from the USDA AMS Socrata dataset acar-e3r8, aggregates Q3
2022-2025 availability by region and year, and injects the result into
divergence_template.html.

The fetch logic here is intentionally duplicated from scripts/fetch_data.py
because that module buckets sub-regions (e.g., INDIANA into Great Lakes),
which is the wrong aggregation for this chart. This script keeps raw
Socrata region names so Indiana, Great Lakes, Mid-Atlantic, etc. each stay
as their own row.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

DATA_SOURCE = os.environ.get("DATA_SOURCE", "csv").strip().lower()
SOCRATA_APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN") or None
CSV_FALLBACK_PATH = os.environ.get(
    "CSV_FALLBACK_PATH", "data/refrigerated_truck_rates_and_availability.csv"
)

SOCRATA_DOMAIN = "agtransport.usda.gov"
DATASET_ID = "acar-e3r8"
API_URL = f"https://{SOCRATA_DOMAIN}/resource/{DATASET_ID}.json"
PAGE_SIZE = 10_000

YEARS = [2022, 2023, 2024, 2025]
YEAR_MIN, YEAR_MAX = YEARS[0], YEARS[-1]
Q3 = 3

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "divergence_template.html"
DEFAULT_OUTPUT = REPO_ROOT / "index.html"

# Region keys we never want in the chart even if Socrata returns them.
# Regions with zero Q3 reports across the window are dropped automatically;
# this set is reserved for explicit excludes.
EXCLUDE_REGIONS = {"OTHER"}


def _get_with_retry(url, *, params, headers, timeout, max_retries=5):
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
    headers: dict[str, str] = {"Accept": "application/json"}
    if SOCRATA_APP_TOKEN:
        headers["X-App-Token"] = SOCRATA_APP_TOKEN

    rows: list[dict[str, Any]] = []
    offset = 0
    where = f"date_extract_y(date) BETWEEN {YEAR_MIN} AND {YEAR_MAX}"
    while True:
        params = {
            "$limit": PAGE_SIZE,
            "$offset": offset,
            "$order": ":id",
            "$where": where,
        }
        print(f"[build_chart] page offset={offset:>7} ",
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
            print("[build_chart] safety cap hit; stopping.", file=sys.stderr)
            break

    if not rows:
        raise ValueError(
            f"Socrata returned 0 rows for {DATASET_ID}. Check that the dataset "
            f"is still published at {API_URL}."
        )

    raw = pd.DataFrame(rows)
    return pd.DataFrame({
        "Week": pd.to_numeric(raw.get("week"), errors="coerce").astype("Int64"),
        "Quarter": pd.to_numeric(raw.get("quarter"), errors="coerce").astype("Int64"),
        "Year": pd.to_numeric(raw.get("year"), errors="coerce").astype("Int64"),
        "Region": raw.get("region", pd.Series(dtype=str))
                     .fillna("").astype(str).str.strip().str.upper(),
        "Availability": pd.to_numeric(raw.get("availability"), errors="coerce"),
    })


def fetch_from_csv() -> pd.DataFrame:
    if not os.path.exists(CSV_FALLBACK_PATH):
        raise FileNotFoundError(
            f"CSV fallback not found at {CSV_FALLBACK_PATH}. Either commit the "
            f"CSV there, or set DATA_SOURCE=api."
        )
    df = pd.read_csv(CSV_FALLBACK_PATH)
    return pd.DataFrame({
        "Week": pd.to_numeric(df.get("Week"), errors="coerce").astype("Int64"),
        "Quarter": pd.to_numeric(df.get("Quarter"), errors="coerce").astype("Int64"),
        "Year": pd.to_numeric(df.get("Year"), errors="coerce").astype("Int64"),
        "Region": df.get("Region", pd.Series(dtype=str))
                    .fillna("").astype(str).str.strip().str.upper(),
        "Availability": pd.to_numeric(df.get("Availability"), errors="coerce"),
    })


def load_data() -> pd.DataFrame:
    src = "api" if DATA_SOURCE == "api" else "csv"
    print(f"[build_chart] source = {src}", file=sys.stderr)
    df = fetch_from_api() if src == "api" else fetch_from_csv()
    df = df.dropna(subset=["Year", "Quarter", "Availability"])
    df = df[df["Region"].astype(bool)]
    df = df[~df["Region"].isin(EXCLUDE_REGIONS)]
    df = df[(df["Year"] >= YEAR_MIN) & (df["Year"] <= YEAR_MAX)]
    df = df[df["Availability"].between(1, 5)]
    if df.empty:
        raise ValueError("After filtering, no rows remain. Check source and filters.")
    print(
        f"[build_chart] {len(df):,} rows, "
        f"years {int(df.Year.min())}-{int(df.Year.max())}, "
        f"{df.Region.nunique()} raw regions",
        file=sys.stderr,
    )
    return df


def display_name(key: str) -> str:
    """ALL CAPS region key to display name.
    PNW stays uppercase (abbreviation). Hyphenated names get title case on
    each part: MID-ATLANTIC -> Mid-Atlantic, MEXICO-ARIZONA -> Mexico-Arizona.
    Everything else gets Python title casing: NEW YORK -> New York,
    GREAT LAKES -> Great Lakes."""
    if key == "PNW":
        return "PNW"
    return "-".join(part.title() for part in key.split("-"))


def aggregate(df: pd.DataFrame) -> dict:
    q3 = df[df["Quarter"] == Q3].copy()
    if q3.empty:
        raise ValueError("No Q3 rows in the data after filtering.")

    regions_all = sorted(q3["Region"].unique())

    def stat(sub: pd.DataFrame) -> dict:
        n = int(len(sub))
        if n == 0:
            return {"mean": None, "n": 0}
        return {"mean": round(float(sub["Availability"].mean()), 3), "n": n}

    stats: dict[str, dict[str, dict]] = {"all": {}}
    stats["all"] = {r: stat(q3[q3["Region"] == r]) for r in regions_all}
    for y in YEARS:
        sub_y = q3[q3["Year"] == y]
        stats[str(y)] = {r: stat(sub_y[sub_y["Region"] == r]) for r in regions_all}

    # Drop regions with zero reports across the full 4-year window.
    kept = [r for r in regions_all if stats["all"][r]["n"] > 0]
    # Tightest (highest mean on the 1=surplus / 5=shortage scale) first.
    kept.sort(key=lambda r: stats["all"][r]["mean"], reverse=True)

    for bucket in stats.values():
        for r in list(bucket.keys()):
            if r not in kept:
                del bucket[r]

    regions_payload = [{"key": r, "name": display_name(r)} for r in kept]

    return {
        "years": YEARS,
        "regions": regions_payload,
        "stats": stats,
    }


# Matches the single-line `const DATA = {...};` injection point in the
# template. `[^;]*` is safe because JSON output never contains semicolons.
_DATA_RE = re.compile(r"const DATA = \{[^;]*\};")


def inject(template: str, data: dict) -> str:
    data_js = json.dumps(data, separators=(",", ":"))
    replacement = f"const DATA = {data_js};"
    new_text, count = _DATA_RE.subn(lambda _: replacement, template, count=1)
    if count != 1:
        raise RuntimeError(
            "Could not find 'const DATA = {...};' in divergence_template.html. "
            "Has the template shape changed?"
        )
    return new_text


def main(out_path: str | None = None) -> None:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found at {TEMPLATE_PATH}")

    df = load_data()
    data = aggregate(df)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = inject(template, data)

    target = Path(out_path) if out_path else DEFAULT_OUTPUT
    if target.parent and str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")

    print(
        f"[build_chart] wrote {target} "
        f"({len(html):,} bytes, {len(data['regions'])} regions, "
        f"{len(data['years'])} years)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
