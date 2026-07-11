# Kinch Ranks

Interactive [Kinch rank](https://www.speedsolving.com/wiki/index.php/KinchRanks) visualizer with filters for region/country, continent, event group, gender, debut year and more.

## Features

- **Full Kinch scoring** — event scores computed as WR / personal record × 100, capped at 100
- **Instant load** — top 1000 from `1000.js` renders immediately; `data.db.gz` (~24 MB) loads async via [sql.js](https://github.com/sql-js/sql.js/)
- **IndexedDB cache** — subsequent visits load the DB from local storage, zero network transfer
- **Precomputed rankings** — top 500 per gender/event-group/clock combo served from a `precomputed` table, instant for most filter combinations
- **Region & country views** — filter rankings against world, country, or continent records
- **Gender & debut year filters** — drill down by male/female and WCA ID year
- **Event grouping** — NxN, big cubes, BLD, non-BLD, other, removed (retired events)
- **Retired events** — toggle 333ft, Magic, Master Magic on/off like Clock; scores computed against their respective WRs
- **Search & sort** — search by name (Enter key or button click, pushed to SQL), sort by any column (via SQL ORDER BY)
- **Profile view** — click any name for detailed event-by-event results with NR/CR/WR ranks, plus a separate table for retired events
- **Statistics view** — a separate page with all-time leaderboards: most podiums, most world records currently held, most world records ever held, most solves, most competitions attended, busiest year, longest active career, and most competitions per country
- **Dark/light mode** — night theme (default) and WCA-inspired day theme
- **9 languages** — English, Portuguese, Spanish, German, Italian, Catalan, Korean, Chinese, Vietnamese

## How it works

The data pipeline (`build.py`) streams the [WCA developer database dump](https://www.worldcubeassociation.org/export/results), extracts personal bests, computes world/country/continent records, selects top entries per country, and outputs:

- `1000.js` (~200 KB) — top 1000 pre-computed entries for the default view. Loads synchronously for instant render.
- `data.db.gz` (~24 MB compressed) — gzipped SQLite database deployed to GitHub Pages. The frontend decompresses it in-browser via `DecompressionStream`, then queries with sql.js. Contains all data: persons, event scores (PBs, ranks, competition IDs, MBF raw scores), records (WR/CWR/conWR baselines), competitions, and precomputed top-500 rankings per filter combination.

The frontend (`index.html`) renders the table immediately from `1000.js` while `data.db.gz` loads asynchronously. On subsequent visits the decompressed DB is served from IndexedDB. Kinch scores are computed on the fly in SQL — no stored columns. Clock and retired events (333ft, Magic, Master Magic) can be toggled on/off; their checkboxes are only shown for All, Other, and Removed event groups.

The Statistics view is powered by a separate script (`calc/other_stats.py`) that streams the same WCA SQL dump and outputs `otherstatistics.js` (`var STATS_DATA = {...}`), loaded synchronously by the frontend. It aggregates all-time leaderboards (podiums, world records held/ever, solves, competitions, busiest year, longest career, per-country competitions) independently of the main Kinch pipeline.

All sorting (including per-event columns), pagination, and search are pushed to SQL. PBs and per-event scores are loaded only for the visible page entries (not all 71k), keeping RAM usage minimal.

No server, no API calls, fully static. Deploys to GitHub Pages.

## Setup (generate your own data)

1. Download the WCA SQL dump: `wca-developer-database-dump.sql`
2. Copy `.env.example` to `.env` and set your paths
3. Run `python3 build.py`

This outputs `data.db`, `data.db.gz`, and `1000.js`.

To regenerate the Statistics view data, run `python3 calc/other_stats.py` (set `SQL_PATH` inside the script to your dump). This outputs `otherstatistics.js`.
