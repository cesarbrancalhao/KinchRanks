# Kinch Ranks — Documentation

## Overview

Kinch Ranks is a data pipeline + static frontend for visualizing WCA Kinch scores. It streams the WCA developer SQL dump (~5GB, ~50M lines) in a single pass, computes personal bests, world/country records, Kinch scores, and outputs static JS files consumed by the frontend. The page loads instantly using a pre-computed top-1000 summary (`1000.js`) while the main dataset (`scores.js`) loads asynchronously. Profile-only data (`profiles.js`) loads separately for progressive enhancement.

---

## build.py — Data Pipeline

### Phases

**Phase 1 — Parse**
Streams the WCA developer SQL dump in a single pass. Extracts the `persons` table (wca_id → name, country) and the `results` table (event_id, person_id, best, average). Keeps only `sub_id=1` persons (the "current" name record) and only events listed in `KINCH_EVENTS_ALL`.

**Phase 2 — Personal bests**
Computes the all-time personal record (minimum valid solve) per person per event, for both single and average. Multi-Blind raw WCA integer values are stored directly (decoded later).

**Phase 3 — World records & country records**
Iterates all PBs to find the best (lowest) single/average per event, both globally (`wr`) and per country (`cwr`) and per continent (`conwr`). MBF records use the Kinch raw score (points + time ratio) rather than the WCA integer.

**Phase 4 — Country-specific Kinch & selection**
For each person, computes Kinch event scores against their country's WR baseline. Persons with fewer than `MIN_EVENTS` non-zero scores are discarded. Per-event scores (`_scores`) and overall (`overall`) are preserved on each entry in the output. The overall is the average of the 17 default events (clock excluded).

Per-country selection (ensuring specialists aren't lost):
- Top 1000 by overall score
- Top 200 per individual event
- Union of both sets → stored in the JSON.

Raw PBs (single/average per event) are written into the JS output so the frontend can recompute scores against any baseline (global or country-specific) and toggle Clock inclusion dynamically.

**Phase 5 — Global pre-computed rankings**
After building all country data, computes Kinch scores for all selected entries using **world records** (not country-specific records). Sorts globally by overall score (default view: World, All events, All genders, no clock). Stores the top 1000 as `precomputed` in the JSON output. This data powers the instant initial table render.

**Phase 6 — Output**
Writes three files:
- `scores.js` — `window.KINCH_SCORES` containing everything needed for the main table (`wr`, `cwr`, `conwr`, `countries` with light pbs (only `s`/`a` times), `precomputed`, `generated_at`)
- `profiles.js` — `window.KINCH_PROFILES` containing profile-only data (`competitions` names, per-person extended `pbs_ext` with competition IDs and NR/CR/WR ranks)
- `1000.js` — `window.KINCH_QUICK` containing the top 1000 pre-computed entries plus world-record baselines for the default view

Output structure:
```json
{
  "wr": { "all": { "single": {...}, "average": {...}, "mbf_score": ... }, "m": {...}, "f": {...} },
  "cwr": { "USA": { "all": {...}, ... }, ... },
  "conwr": { "_Europe": { "all": {...}, ... }, ... },
  "countries": {
    "USA": {
      "name": "USA",
      "count": 200,
      "entries": [
        { "id": "2005XXXX01", "name": "Max Park", "country": "USA",
          "pbs": { "333": {"s": 422, "a": 501}, ... },
          "overall": 85.43 }
      ]
    }
  },
  "precomputed": [
    { "id": "...", "name": "...", "country": "...", "overall": 92.5,
      "events": {"333": 95.0, ...} }
  ]
}
```

The frontend loads this data and computes scores on the fly. When viewing "World" it uses `wr`; when viewing a specific country it uses `cwr[country]`. The Clock checkbox changes the event list length used for the overall average. Extended profile data (`pbs_ext` with competition IDs and NR/CR/WR ranks) lives in `profiles.js` and is merged into `personLookup` on load.

### Event classification

Events are grouped by how their Kinch score is derived:

| Category | Events | Derivation |
|---|---|---|
| `AVERAGE_EVENTS` | 333, 222, 444, 555, 666, 777, 333oh, clock, minx, pyram, skewb, sq1 | `WR_avg / PB_avg × 100` |
| `BETTER_OF_EVENTS` | 333bf, 444bf, 555bf, 333fm | `max(score_from_single, score_from_average)` |
| `MBF_EVENT` | 333mbf | decode WCA multi-blind integer → `(points + time_ratio) / WR_mbf_score × 100` |

`KINCH_EVENTS` is the default 17-event set (clock excluded). `KINCH_EVENTS_ALL` includes clock for data collection; the frontend toggles it.

### Selection tuning

- `MIN_EVENTS = 1` — persons must have at least this many non-zero Kinch scores to be included.
- `TOP_OVERALL = 1000` — guarantee top N by overall score per country.
- `TOP_PER_EVENT = 200` — guarantee top N per individual event per country.
- Final set is the UNION of both guarantees so event specialists (e.g. a 5BLD ace with low overall) are never omitted.

### Key functions

**`decode_mbf(wca_value)`** — decode a WCA multi-blind integer into `(solved, attempted, time_seconds)`. Returns `None` for DNF (-1), DNS (-2), or skipped (0). Logic extracted from the WCA Ruby source (`SolveTime.rb`). Handles both the "old" format (≥ 1e9) and the current format (≤ 9 digits).

**`compute_kinch_mbf(wca_value)`** — compute the raw Kinch MBF score: `(solved − unsolved) + (3600 − min(time_seconds, 3600)) / 3600`. Higher is better.

**`parse_sql_row(line)`** — parse a single SQL VALUES row like `(123,456,'text with spaces',...)`. Handles quoted strings (single quotes, escaped `''`), NULL literals, integers, floats, and bare strings. Deliberately simple to stay fast over 50M+ lines.

**`main()`** — run the full pipeline: parse → PBs → WRs → Kinch → global pre-computed → JSON.

### Scaling notes

- The file is read line-by-line; memory usage is dominated by the persons dict (~300K entries × ~100 bytes ≈ 30MB) and the PBs defaultdict (~300K persons × ~10 events × 60 bytes ≈ 180MB).
- Current single-pass approach processes ~50M lines in ~8 minutes on a consumer SSD.
- For a much larger dataset, consider: using a faster parser (e.g. C-extension CSV reader), splitting the dump and processing chunks in parallel then merging PBs with a min-reduce, or importing into PostgreSQL and running SQL aggregations.

### Per-country selection flow

For each country:
1. Build the set of person indices to include.
2. Top 1000 overall: only persons with ≥ `MIN_EVENTS` qualify.
3. Top 200 per event: anyone with a score in that event qualifies.
4. Union both sets.
5. Sort by overall score, assign ranks.

WR/country-WR data assembled at the top level contains per-gender baselines (`"all"`, `"m"`, `"f"`). The frontend picks the right one based on the gender filter.

---

## index.html — Frontend

### Loading strategy (three-phase)

1. `1000.js` loads synchronously — sets `window.KINCH_QUICK` with top 1000 pre-computed entries + world-record baselines. Small file (~200KB), loads instantly.
2. `scores.js` loads asynchronously via a dynamic `<script>` tag — sets `window.KINCH_SCORES` with the main dataset (~30MB). Unlocks all filters.
3. `profiles.js` loads asynchronously — sets `window.KINCH_PROFILES` with profile-only data (~40MB). Merged into `personLookup` for detailed profile views.

On page load:
- **Quick mode**: renders the table immediately from `KINCH_QUICK`. Country/continent/debut-year filters are shown but disabled with "Loading" text. Gender, event group, clock, search, and page size filters are fully functional.
- **Scores mode** (after `scores.js` loads): all filters are enabled, dropdowns populated with complete country/continent lists and counts. The cache is cleared and the table re-renders with full data.
- **Profiles mode** (after `profiles.js` loads): competition names and NR/CR/WR ranks become available. Clicking a name shows the full profile view with all ranks.

### Data flow

`1000.js`, `scores.js`, and `profiles.js` (all generated by `build.py`) are loaded via `<script>` tags. `KINCH_QUICK` contains pre-computed event scores and overall for the top 1000, so no computation is needed for the default view. `KINCH_SCORES` contains raw personal bests (`pbs` with only `s`/`a` times), plus world-record baselines: global (`wr`), per-country (`cwr`), and per-continent (`conwr`). `KINCH_PROFILES` contains competition names and extended pbs (`pbs_ext` with competition IDs and NR/CR/WR ranks), merged into `personLookup` on load.

For non-default filter combinations, `computeKinch(pbs, wr, activeEvents)` calculates scores on the fly. This allows switching baselines instantly (World vs. country) and toggling the Clock event without re-fetching data.

### Result cache

A `resultsCache` object keyed by filter signature (`country|continent|gender|group|clock|since|until`) stores full sorted entry arrays. Subsequent renders with the same filters skip the expensive `computeKinch` step entirely. The cache is cleared when `scores.js` finishes loading (to ensure fresh pbs from `personLookup`).

### Key functions

| Function | Description |
|---|---|
| `decodeMbf(wca)` | Decode WCA multi-blind integer → raw Kinch score. Returns null for DNF (-1), DNS (-2), or skipped (0). Logic mirrors `decode_mbf` + `compute_kinch_mbf` in `build.py`. |
| `computeKinch(pbs, wr, activeEvents)` | Compute `{ scores, overall }` from raw PBs + WR baseline. Each event score is capped at 100. Overall = average across `activeEvents` (missing events contribute 0). |
| `getWR()` | Returns the right WR baseline. Hierarchy: country > continent > world. |
| `getEntries()` | Collects entries for the current view, filtered by country, continent, gender, and debut year. Falls back to precomputed entries in quick mode. |
| `renderTable()` | Builds/refreshes the HTML table. Uses pre-computed data for default view, result cache for repeated filters, or computes from scratch. Applies column-sort on top of the default overall sort. Paginates with global ranks. |
| `renderPage()` | Fast page-only render — slices cached `_lastEntries` without recomputation. Pre-builds the next page's tbody HTML for instant pagination. |
| `isDefaultFilters()` | Returns true when all filters are at their default values (World, All events, All genders, no clock, full date range). |
| `onScoresLoaded()` | Callback when `scores.js` finishes. Rebuilds `personLookup`, clears cache, enables disabled filters, and re-initializes the UI. Defers if profile view is active. |
| `onProfilesLoaded()` | Callback when `profiles.js` finishes. Merges extended pbs (competition IDs, ranks) into `personLookup` and sets `allData.competitions`. |
| `mergeProfileData()` | Merges `KINCH_PROFILES` (competitions + extended pbs) into `personLookup` and `allData`. Called by both `onScoresLoaded` and `onProfilesLoaded` to handle any load order. |
| `showProfile()` / `hideProfile()` | Toggle between rankings table and single-person profile view. Hide legends/subtitle in profile view. On back, triggers pending full-data refresh if data loaded while profile was open. |
| `setLanguage(lang)` | Switch locale. If profile view is open, closes it first before re-rendering. |

### Event classification (must match build.py)

- `AVERAGE_EVENTS` — use best average (333, 444, mega, pyram, ...)
- `BETTER_OF_EVENTS` — use max(single_score, average_score)
- `333mbf` — use decodeMbf() for points+time ratio

### Visual hints (dark mode)

- Scores ≥ 90: bold
- Scores = 100: gold + bold (world record tier)

### Visual hints (light mode)

- Scores ≥ 90: bold
- Scores = 100: red + bold (world record tier)
- Overall scores: always bold + dark orange

### Column sort behavior

The default sort is by overall score (descending). Column sort is applied on top. The top-200 per-event slice happens AFTER the column sort so that event specialists (e.g. #1 in 5BLD but low overall) surface correctly.

### Pagination & preloading

Default page size is 100. After rendering the current page, the next page's table body HTML is built asynchronously and cached. Clicking "Next" uses the pre-built HTML for an instant transition, then pre-builds the following page.
