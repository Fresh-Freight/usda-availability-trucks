# Q3 Reefer Availability Chart — automated build

GitHub Actions pipeline that pulls USDA refrigerated-truck data and
regenerates the interactive Q3 availability chart, then publishes it to
GitHub Pages.

## What's here

```
.github/workflows/build-chart.yml   # the CI workflow
scripts/fetch_data.py               # data acquisition (API or CSV)
scripts/build_chart.py              # builds the HTML chart
data/refrigerated_truck_rates_and_availability.csv  # CSV fallback
requirements.txt
dist/                               # build output (generated)
```

## One-time setup

### 1. Add the API key as a repository secret
Repo **Settings → Secrets and variables → Actions → New repository secret**

- Name: `USDA_API_KEY` (exact name — the workflow reads this)
- Value: your USDA API key

The key is never printed or committed. It is injected only as an
environment variable inside the Action run.

### 2. Enable GitHub Pages
Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**

After the first successful run, the chart is live at
`https://<your-user>.github.io/<repo>/`.

### 3. Wire in the real API (when ready)
`scripts/fetch_data.py` ships with a working **CSV fallback** so the
pipeline runs immediately. The live API call is a clearly marked
template — it could not be implemented blind because the USDA API's
URL, auth scheme, and response schema were not available during
development.

Fill in the **4 marked spots** in `fetch_from_api()`:
1. the real endpoint URL
2. the auth header/param style your API uses
3. query parameters (date range, dataset, format)
4. response parsing to the canonical columns

Then flip `DATA_SOURCE` to `"api"` in `build-chart.yml` (the `env:`
block of the build step). `_normalize()` enforces the required schema
so a bad response fails loudly in CI rather than silently producing a
wrong chart.

## When it runs

- **On every push to `main`** (primary trigger — rebuilds & redeploys)
- **Manually**, via the *Run workflow* button (`workflow_dispatch`) — lets
  you re-pull data without a commit
- Periodic schedule is commented out in the workflow; uncomment the cron
  if you also want a time-based refresh independent of pushes

Change any of these at the top of `build-chart.yml`.

## Run locally

```bash
pip install -r requirements.txt

# CSV mode (no key needed):
python scripts/build_chart.py dist/Q3_Availability_Graph.html

# API mode (after wiring fetch_from_api):
export USDA_API_KEY=your_key
DATA_SOURCE=api python scripts/build_chart.py dist/Q3_Availability_Graph.html
```

Open `dist/Q3_Availability_Graph.html` in a browser.

## Notes

- The chart design is fixed (the approved Q2-faithful version). Only the
  embedded data changes between builds.
- The data contract is `Week, Quarter, Year, Region, Availability`. As
  long as `fetch_data()` returns those columns, the chart builds.
- Plotly and the fonts load from CDNs at view time, so the published
  page needs internet access in the viewer's browser (standard for
  GitHub Pages).
