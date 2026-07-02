# Kinch Ranks

Interactive [Kinch rank](https://www.speedsolving.com/wiki/index.php/KinchRanks) visualizer with filters for region/country, continent, event group, gender, debut year and more.

## Features

- **Full Kinch scoring** — event scores computed as WR / personal record × 100, capped at 100
- **Instant load** — top 1000 pre-computed rankings render immediately; full dataset loads in background
- **Region & country views** — filter rankings against world or local records
- **Gender & debut year filters** — drill down by male/female and WCA ID year
- **Event grouping** — NxN, big cubes, BLD, non-BLD, other
- **Clock toggle** — include or exclude clock from the overall average
- **Search & sort** — search by name, sort by any column
- **Profile view** — click any name for detailed event-by-event results with NR/CR/WR ranks
- **Dark/light mode** — night theme (default) and WCA-inspired day theme
- **9 languages** — English, Portuguese, Spanish, German, Italian, Catalan, Korean, Chinese, Vietnamese

## How it works

The data pipeline (`build.py`) streams the [WCA developer database dump](https://www.worldcubeassociation.org/export/results), extracts personal bests, computes world/country records, selects top entries per country, and outputs two files:

- `1000.js` (~200KB) — top 1000 pre-computed entries with world-record Kinch scores. Loads instantly for the default view.
- `data.js` (~76MB) — the full dataset loaded asynchronously. Unlocks all filters once ready.

The frontend (`index.html`) renders the table immediately from `1000.js` while `data.js` loads in the background. Country, region and debut-year filters are disabled with a "Loading" placeholder until the full dataset arrives. A result cache avoids recomputing Kinch scores for repeated filter combinations.

No server, no API calls, fully static.

## Setup (generate your own data)

1. Download the WCA SQL dump: `wca-developer-database-dump.sql`
2. Copy `.env.example` to `.env` and set your paths
3. Run `python3 build.py`

This outputs `data.js` and `1000.js`.