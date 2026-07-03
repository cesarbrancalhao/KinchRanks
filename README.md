# Kinch Ranks

Interactive [Kinch rank](https://www.speedsolving.com/wiki/index.php/KinchRanks) visualizer with filters for region/country, continent, event group, gender, debut year and more.

## Features

- **Full Kinch scoring** — event scores computed as WR / personal record × 100, capped at 100
- **Instant load** — top 1000 pre-computed rankings render immediately; full dataset loads in background
- **Lazy Clock** — Clock event data loaded on demand only when toggled, keeping default payload light
- **Region & country views** — filter rankings against world or local records
- **Gender & debut year filters** — drill down by male/female and WCA ID year
- **Event grouping** — NxN, big cubes, BLD, non-BLD, other
- **Search & sort** — search by name, sort by any column
- **Profile view** — click any name for detailed event-by-event results with NR/CR/WR ranks
- **Dark/light mode** — night theme (default) and WCA-inspired day theme
- **9 languages** — English, Portuguese, Spanish, German, Italian, Catalan, Korean, Chinese, Vietnamese

## How it works

The data pipeline (`build.py`) streams the [WCA developer database dump](https://www.worldcubeassociation.org/export/results), extracts personal bests, computes world/country records, selects top entries per country, and outputs four files:

- `1000.js` (~200KB) — top 1000 pre-computed entries with world-record Kinch scores. Loads synchronously for instant default view.
- `scores.js` (~30MB) — full dataset for the main table (world/country/continent records, per-country entries with light PBs — only raw times, no clock). Loads asynchronously, unlocks all filters.
- `profiles.js` (~40MB) — profile-only data (competition names, NR/CR/WR ranks for all events including clock). Loads asynchronously for progressive enhancement.
- `clock.js` (< 1MB) — Clock event times. Loaded on demand only when the user toggles the Clock checkbox.

The frontend (`index.html`) renders the table immediately from `1000.js` while `scores.js` loads. Country, region and debut-year filters are disabled with a "Loading" placeholder until `scores.js` arrives. Profile details (ranks, competition names) become available when `profiles.js` loads. Clock data is fetched lazily on first toggle. A result cache avoids recomputing Kinch scores for repeated filter combinations.

Entries with zero results in all active events are automatically excluded from the table.

No server, no API calls, fully static.

## Setup (generate your own data)

1. Download the WCA SQL dump: `wca-developer-database-dump.sql`
2. Copy `.env.example` to `.env` and set your paths
3. Run `python3 build.py`

This outputs `scores.js`, `profiles.js`, `clock.js`, and `1000.js`.
