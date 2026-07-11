# Kinch Ranks — Documentation

## Overview

Kinch Ranks is a data pipeline + static frontend for visualizing WCA Kinch scores. It streams the WCA developer SQL dump (~5GB, ~50M lines) in a single pass, computes personal bests, world/country/continent records, and outputs a gzipped SQLite database (`data.db.gz`, ~24 MB) consumed by the frontend via [sql.js](https://github.com/sql-js/sql.js/) (SQLite compiled to WebAssembly). All data — persons, event scores, records, ranks, competition names, and precomputed rankings — lives in a single database. The page loads instantly using a pre-computed top-1000 summary (`1000.js`, ~200 KB) while the database loads asynchronously. On subsequent visits the DB loads from IndexedDB (zero network transfer).

---

## build.py — Data Pipeline

### Phases

**Phase 1 — Parse**
Streams the WCA SQL dump in a single pass. Extracts the `persons` table (wca_id → name, country) and the `results` table (event_id, person_id, best, average). Keeps only `sub_id=1` persons.

**Phase 2 — Personal bests**
Computes the all-time personal record per person per event, for both single and average. Multi-Blind raw WCA integers are stored directly (decoded later).

**Phase 3 — World/Country/Continent records**
Iterates all PBs to find the best single/average per event, globally and per country/continent. MBF records use the Kinch raw score.

**Phase 4 — Country-specific Kinch & selection**
Per-country selection: top 1000 by overall + top 200 per event (union of both). Raw PBs, ranks, and competition IDs are stored in the DB.

**Phase 5 — Global pre-computed rankings**
Computes Kinch scores for all selected entries using world records. Top 1000 stored in `1000.js` for instant first render.

**Phase 6 — Output**
Writes three files:

| File | Content | Size |
|---|---|---|
| `1000.js` | Top 1000 pre-computed entries + world-record baselines | ~200 KB |
| `data.db` | SQLite database with all data | ~70 MB |
| `data.db.gz` | Gzipped version deployed to GitHub Pages | ~24 MB |

### Database schema

```sql
CREATE TABLE persons (
    wca_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    country TEXT NOT NULL, continent TEXT NOT NULL,
    gender TEXT NOT NULL, debut_year INTEGER NOT NULL
);

CREATE TABLE event_scores (
    wca_id TEXT NOT NULL, event_id TEXT NOT NULL,
    best_single INTEGER, best_average INTEGER,
    mbf_raw_score REAL,               -- pre-decoded MBF raw score
    single_comp TEXT, average_comp TEXT,
    nr_single INTEGER, nr_average INTEGER,
    cr_single INTEGER, cr_average INTEGER,
    wr_single INTEGER, wr_average INTEGER,
    PRIMARY KEY (wca_id, event_id)
);

CREATE TABLE records (
    scope TEXT NOT NULL, gender TEXT NOT NULL DEFAULT 'all',
    event_id TEXT NOT NULL,
    record_single INTEGER, record_average INTEGER, mbf_score REAL,
    PRIMARY KEY (scope, gender, event_id)
);

CREATE TABLE competitions (
    id TEXT PRIMARY KEY, name TEXT NOT NULL
);

CREATE TABLE precomputed (
    gender TEXT NOT NULL, event_group TEXT NOT NULL,
    include_clock INTEGER NOT NULL, rank INTEGER NOT NULL,
    wca_id TEXT NOT NULL, overall REAL NOT NULL,
    PRIMARY KEY (gender, event_group, include_clock, rank)
);

CREATE TABLE precomputed_totals (
    gender TEXT NOT NULL, event_group TEXT NOT NULL,
    include_clock INTEGER NOT NULL, total_count INTEGER NOT NULL,
    PRIMARY KEY (gender, event_group, include_clock)
);
```

### Event classification

| Category | Events | Kinch derivation |
|---|---|---|---|
| `AVERAGE_EVENTS` | 333, 222, 444, 555, 666, 777, 333oh, clock, 333ft, minx, pyram, skewb, sq1 | `WR_avg / PB_avg × 100` |
| `BETTER_OF_EVENTS` | 333bf, 444bf, 555bf, 333fm | `max(score_single, score_average)` |
| `SINGLE_ONLY_EVENTS` | magic, mmagic | `WR_single / PB_single × 100` (no average format) |
| `MBF_EVENT` | 333mbf | `mbf_raw / WR_mbf × 100` |

### Retired events

Three retired WCA events are parsed and stored in the DB but excluded from default views: **333ft** (3x3 with Feet), **magic** (Magic), and **mmagic** (Master Magic). Each has its own toggle checkbox in the UI (default off), working like the Clock toggle. When any retired event is toggled on, the precomputed path is skipped and on-the-fly SQL is used. Retired events are not precomputed.

### Precomputed rankings

The `precomputed` table stores the top 500 entries for 42 combinations (3 genders × 7 event groups × 2 clock toggle). Excludes country/continent/debut filters. The "removed" group is not precomputed — it always uses the on-the-fly kinch SQL query. The `precomputed_totals` table stores the actual entry count per combination, enabling instant total display in pagination without a COUNT query.

When the user's filters match a precomputed combination and the requested page falls within the stored range (ranks 1–500), the table renders instantly. Pages beyond 500 fall through to the on-the-fly kinch SQL query.

---

## calc/other_stats.py — Statistics Pipeline

A standalone script (independent of `build.py`) that powers the frontend Statistics view. It streams the same WCA SQL dump in a single pass and aggregates all-time leaderboards, writing `otherstatistics.js` as `var STATS_DATA = {...};`.

### Parsing

Uses a hand-rolled `parse_values_line()` to split `INSERT INTO ... VALUES` rows (handling quoted strings, escaped quotes, and `NULL`). A `mode` flag tracks which table's rows are currently being read. Relevant tables: `countries`, `persons`, `competitions`, `round_types`, `ranks_single`, `ranks_average`, `result_attempts`, `results`.

### Computed statistics

| Key | Description | Source |
|---|---|---|
| `podiums` | Most top-3 finishes in final rounds | `results` pos 1–3 in final `round_types` |
| `world_records` | Most world records **currently** held (distinct event+type) | `ranks_single`/`ranks_average` where world rank = 1 |
| `world_records_ever` | Most world records **ever** held (every WR marker over time) | `results.regional_single_record` / `regional_average_record` = `WR` |
| `most_solves` | Most individual solve attempts | `result_attempts` counted per `results` row |
| `most_comps` | Most competitions attended | distinct `competition_id` per person |
| `busiest_year` | Most competitions in a single calendar year | per-person per-year competition counts |
| `longest_career` | Longest span between first and last competition (from 2003) | min/max competition dates per person |
| `comps_by_country` | Top attendees per country (min 20 comps) | per-person per-country competition counts |

`world_records` and `world_records_ever` return the top 20 (fewer if fewer exist); other leaderboards return top 10–15. `assign_ranks()` handles tied ranks (equal values share a rank, next rank skips accordingly).

### Output

Writes `otherstatistics.js` (`var STATS_DATA = {...};`) consumed synchronously by the frontend. `SQL_PATH` and `OUTPUT_PATH` are hardcoded constants at the top of the script.

---

## index.html — Frontend

### Loading strategy

1. `1000.js` loads synchronously — sets `window.KINCH_QUICK` with top 1000 pre-computed entries. ~200 KB, loads instantly. `otherstatistics.js` also loads synchronously — sets `window.STATS_DATA` for the Statistics view.
2. sql.js WASM + `data.db.gz` load asynchronously. The DB is decompressed in-browser via `DecompressionStream`, then cached in IndexedDB for subsequent visits. A loading overlay with spinner covers the controls area until ready.

On page load:
- **Quick mode**: renders top 1000 from `KINCH_QUICK`. Controls covered by loading overlay. Gender, event group, search, page size, and clock are fully functional. Country/continent/debut-year dropdowns are disabled until DB loads.
- **DB mode**: loading overlay hides, all filters enabled. Table re-renders with full DB data.

### Data flow

`build.py` outputs `data.db.gz`. The frontend decompresses it and queries via sql.js. Kinch scores are never stored — they're computed on the fly in SQL using `SUM(CASE WHEN es.event_id = 'X' THEN (expr) ELSE 0 END)`. PBs and per-event scores are loaded only for visible page entries (not all 71k), keeping RAM and SQL parameter limits at bay.

### DB query patterns

| Operation | Method |
|---|---|
| Get entries with overall | Complex SQL: `SUM(CASE WHEN es.event_id = 'X' THEN (kinch_expr) ... END) / N` |
| Precomputed entries | Simple query on `precomputed` table joined with `persons` |
| Precomputed total | O(1) lookup on `precomputed_totals` by primary key |
| Load PBs for page entries | Batched query on `event_scores` (max 980 params per batch) |
| Get WR baseline | Query `records` table by scope + gender |
| Country list | `SELECT country, COUNT(*) FROM persons GROUP BY country` |
| Profile view | `SELECT * FROM event_scores WHERE wca_id = ?` |
| Competitions | Single query on `competitions` table |

### Key functions

| Function | Description |
|---|---|
| `queryAll(sql, params)` | Execute SQL via sql.js prepared statement, return array of row objects. |
| `loadDb()` | Fetch sql.js WASM + `data.db.gz`, decompress, init DB, cache in IndexedDB. |
| `onDbLoaded()` | Hide loading overlay, enable disabled filters, call `init()`. |
| `canUsePrecomputed()` | Returns true when filters match a precomputed combination (no country/continent/debut/search/retired-events, default sort). |
| `getPrecomputedEntries()` | Query `precomputed` table for instant ranked entries. |
| `getPrecomputedTotal()` | O(1) total count from `precomputed_totals`. |
| `getEntries()` | Main entry point: tries precomputed first, falls back to complex kinch SQL for country/continent/debut/search or pages beyond 500. |
| `buildKinchExpr(eventId)` | Builds a per-event SQL kinch expression (MBF, average, better-of, or single-only). |
| `getActiveEvents()` | Returns event list based on selected group + toggled events (clock, retired). Toggles only apply for All/Other/Removed groups. |
| `updateToggleVisibility()` | Shows/hides the Clock toggle and retired-events section based on the selected event group. |
| `loadPbsForEntries(entries, activeEvents)` | Batched query loading raw PBs only for visible page entries. |
| `ensurePersonInLookup(wcaId)` | Lazy-load a person's full data from DB for profile view. |
| `getWR()` | Query records table for scope/gender baseline; fall back to `KINCH_QUICK.wr` in quick mode. |
| `renderTable()` | Renders HTML table. Quick mode uses `KINCH_QUICK`; otherwise pbs+events loaded only for current page. |
| `showProfile()` / `hideProfile()` | Toggle between rankings table and single-person profile view. Uses DB for all data. |

### Column sort

Sorting is pushed entirely to SQL. Clicking the overall, name, or any event column rebuilds the query with the appropriate `ORDER BY` clause. For per-event columns, the sort expression uses `SUM(CASE WHEN es.event_id = 'X' THEN (expr) ELSE 0 END)`.

### Pagination

Entry count comes from `entries.length` (complex SQL or precomputed). When precomputed path is used, the real total from `precomputed_totals` is shown. Pages beyond the precomputed range (500) automatically fall through to the complex SQL.

### Search

Name search triggers only on Enter key or clicking the adjacent Search button — not on every keystroke — to avoid heavy SQL queries while typing.

### Profile view

Clicking a person's name loads their full event-by-event results. Active events are shown in the "Results" table; retired events (333ft, magic, mmagic) appear in a separate "Removed" table below it, only if the person has any.

### Statistics view

A "Statistics" button in the top bar opens a separate all-time leaderboards page (`#statsView`), backed by `STATS_DATA` from `otherstatistics.js` (loaded synchronously alongside `1000.js`). It requires no database — everything is precomputed by `calc/other_stats.py`.

| Function | Description |
|---|---|
| `showStats()` | Hides the rankings UI (controls, table, pagination, legends, profile) and renders the stats page. |
| `hideStats()` | Restores the rankings view. |
| `renderStats()` | Builds all leaderboard tables from `STATS_DATA` plus the per-country dropdown. |
| `statTable(title, data, valLabel, showDetail)` | Renders a single ranked leaderboard table; `showDetail` appends `p.detail` to the value (used for busiest year / longest career). |
| `updateCountryStat()` | Re-renders the "Most Competitions per Country" table when the country dropdown changes. |

Leaderboards shown: Most Podiums, Most World Records Held, Most World Records Ever, Most Solves Ever, Most Competitions Attended, Busiest Year, Longest Active Career, and Most Competitions Attended per Country.
