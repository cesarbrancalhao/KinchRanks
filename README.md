# Kinch Ranks

Interactive [Kinch rank](https://www.speedsolving.com/wiki/index.php/KinchRanks) visualizer but with better filters, search by country, continent, event group, gender, debut year and more.

## Features

- **Full Kinch scoring** — event scores computed as WR / personal record × 100, capped at 100
- **Country & continent views** — filter rankings against world or local records
- **Gender & debut year filters** — drill down by male/female and WCA ID year
- **Event grouping** — NxN, big cubes, BLD, non-BLD, other
- **Clock toggle** — include or exclude clock from the overall average (since its getting bonked)
- **Dark/light mode** — night theme (default) and WCA-inspired day theme

## How it works

The data pipeline (`build.py`) streams the [WCA developer database dump](https://www.worldcubeassociation.org/export/results), extracting personal bests per person per event. It then computes world and country records, selects the top entries per country, and outputs `data.js`.

The `index.html` loads `data.js` and computes Kinch scores on the fly, no server, no API calls, fully static (this was done this way because I'm not getting a penny from this ok, don't complain).

## Setup (if you want to generate your own data)

1. Download the WCA SQL dump: `wca-developer-database-dump.sql`
2. Copy `.env.example` to `.env` and set your paths
3. Run `python3 build.py`

This outputs `data.js` and `data.json` (standalone JSON).